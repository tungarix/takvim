"""Wi-Fi eşleştirme: aynı ağdaki telefon için KISA ÖMÜRLÜ yerel HTTPS sunucusu.

Protokol ve tehdit modeli: `docs/senkron-wifi.md` (bağlayıcı). Biçim ve birleştirme
kuralları `docs/senkron.md` + `ice.py`; burası yalnızca dosyanın NASIL taşındığı.

Bu modül `ui/`yi bilmez (AGENTS §2); ui tarafı `WifiYonetici`yi sarar. Sert kurallar,
hepsinin testi var (`tests/test_senkron_wifi.py`):

- Yalnız seçilen ÖZEL IPv4'e bağlanır, `0.0.0.0`'a ASLA. Üretim yolu yalnız spec §3
  aralıklarını kabul eder; `test_ipleri` (yalnız testler/geliştirici betiği) dışında
  gevşetme yoktur ve belirsiz adres (`0.0.0.0`) orada da reddedilir.
- Sertifika ve özel anahtar bellekte üretilir. `ssl` yalnız dosyadan yükleyebildiği
  için anahtar PARAŞÜTLE (rastgele parolayla şifreli PEM) milisaniyeliğine geçici
  dosyaya yazılıp yüklenir yüklenmez silinir; parola hiçbir yere yazılmaz.
- Token ve dosya içeriği ASLA günlüğe yazılmaz (günlük: açıldı/kapandı, istek sayısı,
  sonuç).
- Kimlik doğrulama HER ŞEYDEN ÖNCE: yetkisiz isteğe yol/metot bilgisi sızmaz.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import hmac
import ipaddress
import json
import math
import os
import secrets
import socket
import socketserver
import ssl
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

from store import Repo

from .disa import durum_uret, json_metni
from .ice import SenkronHatasi, dogrula, ice_aktar

__all__ = [
    "WifiHatasi",
    "WifiOturumu",
    "WifiYonetici",
    "ozel_ip_mi",
    "varsayilan_ip_bul",
]

BAGLANTI_TABANI = "https://aktenak.tech/s"
OMUR_SN = 180               # en çok 3 dakika
KARAR_SN = 60               # masaüstü onayı için en çok 60 sn
MAKS_HATA = 5               # bir kaynak IP'nin bu kadar başarısız kimlik denemesinden sonra o IP engellenir
MAKS_TOPLAM_HATA = 50       # tüm IP'lerden toplam bu kadar başarısızlıkta oturum kapanır (yedek fren)
EN_COK_IP_BAGLANTI = 2      # aynı kaynak IP'den eşzamanlı bağlantı
MAKS_GOVDE = 16 * 1024 * 1024
EN_COK_BAGLANTI = 8         # eşzamanlı bağlantı: yavaş istemciler thread yığmasın
ISTEK_ZAMAN_ASIMI = 15      # her soket okuması için sn (kimliği doğrulanmış istemci)
KIMLIKSIZ_OMUR_SN = 10      # kimlik doğrulanana dek bağlantının TOPLAM ömrü (TLS dahil; damlatan istemci yuva tutamasın)
GOVDE_OMUR_SN = 30          # kimlik doğrulandıktan sonra isteğin GÖVDESİNİ okumak için toplam süre
ATILAN_GOVDE = 1024 * 1024  # reddedilen isteğin okunup atılan gövdesi (RST yanıtı ezmesin)
PORT_ARALIGI = (49152, 65535)
AD_UZUNLUGU = 40

# Spec §3: yalnız özel (RFC 1918) ve link-local aralıklar. `ipaddress.is_private`
# KULLANILMIYOR: loopback, 100.64/10 vb. de "özel" sayar.
_OZEL_AGLAR = tuple(
    ipaddress.ip_network(a)
    for a in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
)


class WifiHatasi(ValueError):
    """Eşleştirme başlatılamadı; `kod` ön yüzün `hata_<kod>` şablonunu seçer."""

    def __init__(self, kod: str, mesaj: str, param: dict | None = None) -> None:
        super().__init__(mesaj)
        self.kod = kod
        self.param = param


def ozel_ip_mi(ip: str) -> bool:
    """IPv4 özel (10/8, 172.16/12, 192.168/16) ya da link-local (169.254/16) mi."""
    try:
        adres = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return any(adres in ag for ag in _OZEL_AGLAR)


def varsayilan_ip_bul() -> str:
    """Varsayılan yoldaki (default route) arayüzün IPv4'ü.

    UDP soketini `connect` etmek paket GÖNDERMEZ, yalnızca işletim sistemine hangi
    yerel adresle çıkacağını sordurur. 192.0.2.1 TEST-NET-1: hiçbir yerde gerçek
    değil ama varsayılan yoldan geçer. Yol yoksa (ağ kapalı) `OSError`.
    """
    soket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        soket.connect(("192.0.2.1", 9))
        ip = soket.getsockname()[0]
    except OSError:
        raise WifiHatasi("wifi_ag_yok", "ağ bağlantısı bulunamadı") from None
    finally:
        soket.close()
    if ip == "0.0.0.0":
        raise WifiHatasi("wifi_ag_yok", "ağ bağlantısı bulunamadı")
    return ip


def _gecici_sil(yol: str) -> None:
    """Geçici PEM'i siler. Virüs tarayıcısı vb. dosyayı kilitleyip silmeyi engellese bile eşleştirme
    BAŞLAMAMAZLIK etmez: anahtar zaten rastgele parolayla şifreli ve geçici klasörde; kısa süre
    yeniden denenir, olmazsa uygulama çıkışında silinir."""
    for _ in range(5):
        try:
            os.unlink(yol)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)
    atexit.register(_sessiz_sil, yol)


def _sessiz_sil(yol: str) -> None:
    try:
        os.unlink(yol)
    except OSError:
        pass


def sertifika_uret(ip: str) -> tuple[ssl.SSLContext, str]:
    """Bellekte kendi imzalı ECDSA P-256 sertifika üretir; (TLS bağlamı, parmak izi) verir.

    SAN = `ip`, 1 gün geçerli (5 dk geriye: telefon saati geri kalırsa istemci
    "henüz geçerli değil" demesin). Parmak izi = DER'in SHA-256'sı, base64url
    dolgusuz (43 karakter); QR'daki `f` ve istemcinin sabitlediği değer.
    `cryptography` burada İÇERİDEN import edilir: yalnızca Wi-Fi eşleştirme ister,
    `senkron` paketinin geri kalanı (ve açılış) onsuz da yüklenir.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    anahtar = ec.generate_private_key(ec.SECP256R1())
    ad = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Takvim")])
    simdi = datetime.now(UTC)
    sertifika = (
        x509.CertificateBuilder()
        .subject_name(ad)
        .issuer_name(ad)
        .public_key(anahtar.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(simdi - timedelta(minutes=5))
        .not_valid_after(simdi + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.IPv4Address(ip))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(anahtar, hashes.SHA256())
    )
    parmak = base64.urlsafe_b64encode(
        hashlib.sha256(sertifika.public_bytes(serialization.Encoding.DER)).digest()
    ).rstrip(b"=").decode("ascii")

    parola = secrets.token_hex(16).encode("ascii")
    pem = sertifika.public_bytes(serialization.Encoding.PEM) + anahtar.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(parola),
    )
    baglam = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    baglam.minimum_version = ssl.TLSVersion.TLSv1_2
    # `ssl` belleğten yükleyemiyor: şifreli PEM geçici dosyaya, yüklenince HEMEN silinir.
    fd, yol = tempfile.mkstemp(prefix="takvim-wifi-", suffix=".pem")
    try:
        with os.fdopen(fd, "wb") as dosya:
            dosya.write(pem)
        baglam.load_cert_chain(yol, password=parola)
    finally:
        _gecici_sil(yol)
    return baglam, parmak


def _yaz(metin: str) -> None:
    """Varsayılan günlük: projedeki gibi `print` (paketli uygulamada takvim.log'a gider)."""
    print(metin, flush=True)


_YETKISIZ = {"error": "yetkisiz"}


class WifiOturumu:
    """TEK bir eşleştirme oturumu: sunucu + durum makinesi. Kullanımdan sonra atılır.

    Aşamalar: `bekliyor` (telefon bekleniyor) -> `onay_bekliyor` (geçerli dosya geldi,
    masaüstünde karar bekleniyor) -> `isleniyor` (onaylandı, birleştiriliyor) ->
    `bitti` (`sonuc` dolu). `zaman` testlerde enjekte edilir (saniye, monoton).
    """

    def __init__(
        self,
        *,
        ip: str,
        depo_ac: Callable[[], AbstractContextManager[Repo]],
        cihaz_adi: str,
        cihaz_id: str,
        uygulama: str,
        zaman: Callable[[], float] = time.monotonic,
        gunluk: Callable[[str], None] = _yaz,
        test_ipleri: frozenset[str] = frozenset(),
    ) -> None:
        if ipaddress.ip_address(ip).is_unspecified:
            raise ValueError("belirsiz adrese (0.0.0.0) bağlanılmaz")
        if not (ozel_ip_mi(ip) or ip in test_ipleri):
            raise WifiHatasi("wifi_ozel_ag_degil", "özel bir ağa bağlı değilsin")
        self.ip = ip
        self.port = 0
        self.cihaz_adi = cihaz_adi
        self.cihaz_id = cihaz_id
        self.uygulama = uygulama
        self.depo_ac = depo_ac
        self._zaman = zaman
        self._gunluk = gunluk
        self._token = secrets.token_hex(16)  # 128 bit, 32 küçük hex
        self._kilit = threading.Condition()
        self._bitti = threading.Event()
        self.faz = "bekliyor"
        self.sonuc: str | None = None
        self.rapor: dict | None = None
        self.ozet: dict | None = None
        self.hata_sayisi = 0
        self.hata_ip: dict[str, int] = {}
        self.engelli: set[str] = set()
        self._post_var = False
        self.istek_sayisi = 0
        self.baglanti_hatasi = 0
        self._karar: bool | None = None
        self._bitis = 0.0
        self._karar_bitis = 0.0
        self._httpd: _Sunucu | None = None
        self._thread: threading.Thread | None = None
        self.parmak_izi = ""
        self.baglanti = ""

    # -- yaşam döngüsü ------------------------------------------------------

    def baslat(self) -> None:
        """Sertifikayı üretir, rastgele bir boş porta bağlanır ve sunucuyu başlatır."""
        baglam, self.parmak_izi = sertifika_uret(self.ip)
        lo, hi = PORT_ARALIGI
        son: OSError | None = None
        for _ in range(30):
            port = lo + secrets.randbelow(hi - lo + 1)
            try:
                self._httpd = _Sunucu((self.ip, port), self, baglam)
            except OSError as hata:  # port dolu / izin yok: başka port dene
                son = hata
                continue
            break
        else:
            raise WifiHatasi("wifi_baslatilamadi", "eşleştirme sunucusu başlatılamadı") from son
        self.port = self._httpd.server_address[1]
        self._bitis = self._zaman() + OMUR_SN
        ad = quote(self.cihaz_adi[:AD_UZUNLUGU], safe="")
        self.baglanti = (
            f"{BAGLANTI_TABANI}#v=1&h={self.ip}:{self.port}&t={self._token}"
            f"&f={self.parmak_izi}&n={ad}"
        )
        self._thread = threading.Thread(target=self._dongu, name="wifi-sunucu", daemon=True)
        self._thread.start()
        self._httpd.dongu_basladi.wait(2)
        threading.Thread(target=self._bekcisi, name="wifi-bekci", daemon=True).start()
        self._gunluk("wifi: oturum açıldı")

    def _dongu(self) -> None:
        httpd = self._httpd
        assert httpd is not None
        try:
            httpd.serve_forever(poll_interval=0.1)
        finally:
            httpd.server_close()

    def _bekcisi(self) -> None:
        """Süreyi izler. Onay beklerken karar döngüsü kendi süresini yönetir."""
        while not self._bitti.wait(0.1):
            if self.faz == "bekliyor" and self.sure_doldu():
                self.bitir("sure_doldu")

    def sure_doldu(self) -> bool:
        """3 dakikalık ömür doldu mu."""
        return self._zaman() >= self._bitis

    def bitir(self, sonuc: str, rapor: dict | None = None) -> None:
        """Oturumu kapatır: token ölür, port kapanır. Birden çok çağrı zararsız."""
        with self._kilit:
            if self.faz == "bitti":
                return
            self.faz = "bitti"
            self.sonuc = sonuc
            self.rapor = rapor
            self._kilit.notify_all()
            istek, hata = self.istek_sayisi, self.baglanti_hatasi
        self._bitti.set()
        self._gunluk(f"wifi: oturum kapandı (sonuç={sonuc}, istek={istek}, bağlantı hatası={hata})")
        httpd, thread = self._httpd, self._thread
        if httpd is not None and thread is not None and thread is not threading.current_thread():
            httpd.shutdown()
            thread.join(3)

    # -- kimlik -------------------------------------------------------------

    def yetkili_mi(self, baslik: str | None) -> bool:
        """`Authorization: Bearer <t>` sabit zamanlı karşılaştırılır."""
        sunulan = baslik[7:] if baslik and baslik.startswith("Bearer ") else ""
        gecerli = hmac.compare_digest(sunulan.encode("utf-8", "replace"), self._token.encode("ascii"))
        return gecerli and self.faz != "bitti"

    def basarisiz(self, ip: str) -> None:
        """Başarısız kimlik doğrulamasını KAYNAK IP başına sayar: `MAKS_HATA`'ya varan IP o oturum
        boyunca engellenir (oturum AÇIK kalır; ağdaki biri tokensız isteklerle eşleştirmeyi bozamasın).
        Toplam `MAKS_TOPLAM_HATA`'yı aşarsa (çok sayıda IP'den dağınık saldırı) oturum kapanır."""
        with self._kilit:
            self.hata_sayisi += 1
            n = self.hata_ip[ip] = self.hata_ip.get(ip, 0) + 1
            if n >= MAKS_HATA:
                self.engelli.add(ip)
            oldu = self.hata_sayisi >= MAKS_TOPLAM_HATA
        if oldu:
            self.bitir("cok_hata")

    def engelli_mi(self, ip: str) -> bool:
        with self._kilit:
            return ip in self.engelli

    def post_ayir(self) -> str:
        """`dogrula`dan ÖNCE: oturumda aynı anda en çok BİR doğrulanan/onay bekleyen POST olur.
        `tamam | mesgul | kapandi` döner; `tamam`ı alan `post_birak` ya da onay yoluyla bırakır."""
        with self._kilit:
            if self.faz == "bitti":
                return "kapandi"
            if self.faz != "bekliyor" or self._post_var:
                return "mesgul"
            self._post_var = True
            return "tamam"

    def post_birak(self) -> None:
        with self._kilit:
            self._post_var = False

    def iptal(self) -> None:
        """Kullanıcı İptal'i. Onaydan sonra birleştirme sürerken (`isleniyor`) YOK SAYILIR: veri
        birleşecek, sonuç "iptal" diye yanlış yazılmasın."""
        with self._kilit:
            if self.faz == "isleniyor":
                return
        self.bitir("iptal")

    def istek_say(self) -> None:
        with self._kilit:
            self.istek_sayisi += 1

    # -- masaüstü onayı -----------------------------------------------------

    def onay_iste(self, ozet: dict) -> str:
        """Geçerli dosya geldi: arayüzde karar bekler. `onay|red|zaman|mesgul|kapandi` döner.

        Bekleme POST'un alındığı andan itibaren `KARAR_SN`'dir; oturumun kapanış süresi
        gerekirse onay bitene kadar uzar (en çok +`KARAR_SN`), çünkü kullanıcıya her
        zaman tam süre tanınır (spec §3).
        """
        with self._kilit:
            if self.faz != "bekliyor":
                return "mesgul" if self.faz != "bitti" else "kapandi"
            self.faz = "onay_bekliyor"
            self.ozet = ozet
            self._karar = None
            self._karar_bitis = self._zaman() + KARAR_SN
            self._bitis = max(self._bitis, self._karar_bitis)
            while self._karar is None and self.faz == "onay_bekliyor":
                kalan = self._karar_bitis - self._zaman()
                if kalan <= 0:
                    return "zaman"
                self._kilit.wait(min(kalan, 0.1))
            if self.faz == "bitti":
                return "kapandi"
            return "onay" if self._karar else "red"

    def karar_ver(self, onay: bool) -> None:
        """Arayüzden gelen Birleştir/Reddet kararı."""
        with self._kilit:
            if self.faz != "onay_bekliyor" or self._karar is not None:
                raise WifiHatasi("wifi_karar_yok", "bekleyen bir karar yok")
            self._karar = onay
            self.faz = "isleniyor" if onay else "onay_bekliyor"
            self._kilit.notify_all()

    # -- durum --------------------------------------------------------------

    def durum(self) -> dict:
        """Arayüzün yoklaması için durum. Token BURADA dönmez."""
        with self._kilit:
            bitti = self.faz == "bitti"
            return {
                "asama": self.faz,
                "kalan_sn": 0 if bitti else max(0, math.ceil(self._bitis - self._zaman())),
                "karar_kalan_sn": (
                    max(0, math.ceil(self._karar_bitis - self._zaman()))
                    if self.faz in ("onay_bekliyor", "isleniyor") else 0
                ),
                "ozet": self.ozet if self.faz in ("onay_bekliyor", "isleniyor") else None,
                "sonuc": self.sonuc,
                "rapor": self.rapor,
            }


class _Sunucu(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Tek oturumluk, thread'li TLS sunucusu.

    `HTTPServer` DEĞİL: onun `server_bind`i `socket.getfqdn` çağırıp Windows'ta
    saniyelerce ters DNS bekleyebiliyor. Thread'li, çünkü POST masaüstü onayını
    bekliyor (60 sn) ve bu sürede başka istekler tıkanmamalı. TLS el sıkışması
    KABUL döngüsünde değil istek thread'inde (`_Istek.setup`): yarım kalan bir
    el sıkışması yeni bağlantıları engellemesin.
    """

    daemon_threads = True
    allow_reuse_address = False  # Windows'ta SO_REUSEADDR dinlenen porta bind'e izin verir
    request_queue_size = 16

    def __init__(self, adres: tuple[str, int], oturum: WifiOturumu, baglam: ssl.SSLContext) -> None:
        self.oturum = oturum
        self.baglam = baglam
        self.dongu_basladi = threading.Event()
        self._yuva = threading.BoundedSemaphore(EN_COK_BAGLANTI)
        self._ip_kilit = threading.Lock()
        self._ip_baglanti: dict[str, int] = {}
        super().__init__(adres, _Istek)

    def service_actions(self) -> None:
        self.dongu_basladi.set()

    def process_request(self, request, client_address) -> None:  # type: ignore[override]
        ip = client_address[0]
        if self.oturum.engelli_mi(ip):  # çok sayıda başarısız denemeli IP: yanıtsız, hemen kapat
            self.shutdown_request(request)
            return
        if not self._yuva.acquire(blocking=False):
            self.shutdown_request(request)  # kapasite dolu: yanıtsız bırak
            return
        with self._ip_kilit:
            if self._ip_baglanti.get(ip, 0) >= EN_COK_IP_BAGLANTI:
                self._yuva.release()
                self.shutdown_request(request)  # tek IP bütün yuvaları dolduramasın
                return
            self._ip_baglanti[ip] = self._ip_baglanti.get(ip, 0) + 1
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address) -> None:  # type: ignore[override]
        try:
            super().process_request_thread(request, client_address)
        finally:
            ip = client_address[0]
            with self._ip_kilit:
                kalan = self._ip_baglanti.get(ip, 1) - 1
                if kalan > 0:
                    self._ip_baglanti[ip] = kalan
                else:
                    self._ip_baglanti.pop(ip, None)
            self._yuva.release()

    def handle_error(self, request, client_address) -> None:  # type: ignore[override]
        # Hatanın İÇERİĞİ (adres, iz) günlüğe girmez; yalnızca sayılır.
        self.oturum.baglanti_hatasi += 1


class _Istek(BaseHTTPRequestHandler):
    """`/v1/hello` ve `/v1/state` uçları. CORS başlığı HİÇ yazılmaz."""

    protocol_version = "HTTP/1.1"
    timeout = ISTEK_ZAMAN_ASIMI
    # `Expect: 100-continue` HTTP/1.0 istekte `handle_expect_100`e hiç uğramaz: kimliğin
    # doğrulandığı bayrakla izlenir, başlığa güvenilmez.
    _kimlikli = False
    _govde_okundu = False

    _sayac: threading.Timer | None = None

    def setup(self) -> None:
        self.request.settimeout(ISTEK_ZAMAN_ASIMI)
        # El sıkışması AYRI yapılır: sayaç, `self.request` SSLSocket olduktan sonra kurulabilsin.
        self.request = self.server.baglam.wrap_socket(  # type: ignore[attr-defined]
            self.request, server_side=True, do_handshake_on_connect=False)
        self._sayac_kur(KIMLIKSIZ_OMUR_SN)
        try:
            self.request.do_handshake()
            super().setup()
        except BaseException:
            self._sayaci_durdur()
            raise

    def _sayaci_durdur(self) -> None:
        if self._sayac is not None:
            self._sayac.cancel()

    def _sayac_kur(self, sn: float) -> None:
        self._sayaci_durdur()
        self._sayac = threading.Timer(sn, self._kimliksizi_kes)
        self._sayac.daemon = True
        self._sayac.start()

    def _kimliksizi_kes(self) -> None:
        """Toplam süre doldu (takılı el sıkışma, damlatılan başlık ya da gövde): bağlantıyı kopar.
        `SSLSocket.shutdown` değil temel soketinki: SSL durumuna başka thread'den dokunulmaz."""
        try:
            socket.socket.shutdown(self.request, socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self) -> None:
        self._sayaci_durdur()
        super().finish()
        try:
            self.connection.close()  # SSLSocket'i ilk soket sarmaladı: kapanışı biz yapıyoruz
        except OSError:
            pass

    def log_message(self, format: str, *args) -> None:
        """Erişim günlüğü YOK (yol/istemci adresi bile yazılmaz)."""

    def version_string(self) -> str:
        return "takvim"

    def send_error(self, code, message=None, explain=None) -> None:  # type: ignore[override]
        # Python'un HTML hata sayfaları yerine JSON. 501 (bilinmeyen metot) da
        # yetkisiz isteğe 401'den farklı bir şey söylemesin: normal akışa girer.
        if code == 501 and hasattr(self, "headers"):
            self._isle(self.command or "")
            return
        self.close_connection = True
        self._yanit(code, {"error": "gecersiz_istek"})

    # Hangi metot gelirse gelsin tek yol: kimlik, sonra yol, sonra metot.
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = (
        lambda self: self._isle(self.command)
    )

    @property
    def _oturum(self) -> WifiOturumu:
        return self.server.oturum  # type: ignore[attr-defined]

    def _yanit(self, kod: int, govde: dict | bytes, ekler: dict | None = None) -> None:
        ham = govde if isinstance(govde, bytes) else json.dumps(govde, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(ham)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for ad, deger in (ekler or {}).items():
            self.send_header(ad, deger)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(ham)
        self.close_connection = True
        self._kalan_govdeyi_at()

    def _kalan_govdeyi_at(self) -> None:
        """Okunmamış küçük gövdeyi atar: okunmadan kapatılan bağlantıda TCP sıfırlaması
        (RST) yanıtı ezer ve istemci 401/405 yerine bağlantı hatası görür (kural 77'deki
        aynı tuzak). `ATILAN_GOVDE`'den büyük gövde okunmaz: o istemci zaten kötü niyetli
        ya da bozuk; bağlantı kesilir."""
        if self._govde_okundu:
            return
        self._govde_okundu = True
        ham = getattr(self, "headers", None) and self.headers.get("Content-Length", "")
        if ham and ham.strip().isdecimal() and 0 < int(ham) <= ATILAN_GOVDE:
            try:
                self.rfile.read(int(ham))
            except (OSError, ValueError):
                pass

    def _kimlik_dogrula(self) -> bool:
        """Oturum açık ve token doğru mu. Yanlışsa 401 yazar, sayacı artırır."""
        o = self._oturum
        # Yalnız `bekliyor`da: onay beklerken süreyi `onay_iste` (408) yönetir.
        if o.faz == "bekliyor" and o.sure_doldu():
            o.bitir("sure_doldu")
        if o.engelli_mi(self.client_address[0]):
            self.close_connection = True  # engelli IP: yanıt yok
            return False
        if o.faz == "bitti":
            self._yanit(401, _YETKISIZ)
            return False
        if not o.yetkili_mi(self.headers.get("Authorization")):
            o.basarisiz(self.client_address[0])
            self._yanit(401, _YETKISIZ)
            return False
        # Kimlik tamam: yalnız POST gövdesini okumak için toplam süre sınırı kalır (onay beklemesi
        # ve yanıt yazımı süreyle kesilmez).
        if self.command == "POST":
            self._sayac_kur(GOVDE_OMUR_SN)
        else:
            self._sayaci_durdur()
        return True

    def handle_expect_100(self) -> bool:
        # `100 Continue`yi yetkisiz ya da aşırı büyük gövdeye VERME: istemci göndermeye başlamasın.
        self._oturum.istek_say()
        if not self._kimlik_dogrula():
            return False
        self._kimlikli = True
        uzunluk = self.headers.get("Content-Length", "")
        if uzunluk.strip().isdecimal() and int(uzunluk) > MAKS_GOVDE:
            self._yanit(413, {"error": "cok_buyuk"})
            return False
        return super().handle_expect_100()

    def _isle(self, metot: str) -> None:
        self.close_connection = True
        if not self._kimlikli:
            self._oturum.istek_say()
            if not self._kimlik_dogrula():
                return
        yol = self.path.split("?", 1)[0]
        rotalar: dict[str, dict[str, Callable[[], None]]] = {
            "/v1/hello": {"GET": self._hello},
            "/v1/state": {"GET": self._durum_ver, "POST": self._durum_al},
        }
        if yol not in rotalar:
            self._yanit(404, {"error": "yok"})
            return
        if metot not in rotalar[yol]:
            self._yanit(405, {"error": "metot"}, {"Allow": ", ".join(rotalar[yol])})
            return
        try:
            rotalar[yol][metot]()
        except (ConnectionError, TimeoutError, ssl.SSLError):
            raise
        except Exception as hata:  # içerik sızmasın: yalnızca tür
            self._oturum._gunluk(f"wifi: iç hata ({type(hata).__name__})")
            if not self.wfile.closed:
                self._yanit(500, {"error": "sunucu_hatasi"})

    def _hello(self) -> None:
        o = self._oturum
        self._yanit(200, {
            "format": "takvim-wifi",
            "version": 1,
            "device": {"name": o.cihaz_adi, "app": o.uygulama},
        })

    def _durum_ver(self) -> None:
        """GET /v1/state: masaüstünün TAM durumu (`.takvimsync`)."""
        o = self._oturum
        with o.depo_ac() as repo:
            durum = durum_uret(repo, cihaz_id=o.cihaz_id, cihaz_adi=o.cihaz_adi, uygulama=o.uygulama)
        self._yanit(200, json_metni(durum).encode("utf-8"))

    def _durum_al(self) -> None:
        """POST /v1/state: telefonun durumu; masaüstü onayından sonra birleştirilir."""
        o = self._oturum
        if self.headers.get("Transfer-Encoding") is not None:
            self._yanit(411, {"error": "uzunluk_gerekli"})
            return
        ham = self.headers.get("Content-Length")
        if ham is None:
            self._yanit(411, {"error": "uzunluk_gerekli"})
            return
        if not ham.strip().isdecimal():
            self._yanit(400, {"error": "uzunluk_gecersiz"})
            return
        uzunluk = int(ham)
        if uzunluk > MAKS_GOVDE:  # gövdeyi OKUMADAN reddet
            self._yanit(413, {"error": "cok_buyuk"})
            return
        govde = self.rfile.read(uzunluk)
        self._govde_okundu = True
        self._sayaci_durdur()  # gövde tamam: onay beklemesi süreyle kesilmez
        if len(govde) < uzunluk:
            self._yanit(400, {"error": "govde_eksik"})
            return
        # Pahalı doğrulamadan ÖNCE: oturumda aynı anda tek POST (ikincisi CPU yedirmesin).
        yer = o.post_ayir()
        if yer != "tamam":
            self._yanit(409, {"error": "mesgul" if yer == "mesgul" else "iptal"})
            return
        try:
            ozet = dogrula(govde)
        except SenkronHatasi as hata:
            o.post_birak()
            self._yanit(400, {"error": hata.kod, "message": str(hata), "param": hata.param})
            return
        except BaseException:
            o.post_birak()
            raise
        sonuc = o.onay_iste(ozet)
        if sonuc == "mesgul":
            self._yanit(409, {"error": "mesgul"})
        elif sonuc == "kapandi":
            self._yanit(409, {"error": "iptal"})
        elif sonuc == "red":
            self._yanit(403, {"error": "reddedildi"})
            o.bitir("reddedildi")
        elif sonuc == "zaman":
            self._yanit(408, {"error": "zaman_asimi"})
            o.bitir("zaman_asimi")
        else:
            self._birlestir(govde)

    def _birlestir(self, govde: bytes) -> None:
        o = self._oturum
        try:
            with o.depo_ac() as repo:
                rapor = ice_aktar(repo, govde).as_dict()
        except SenkronHatasi as hata:
            self._yanit(400, {"error": hata.kod, "message": str(hata), "param": hata.param})
            o.bitir("hata")
            return
        except Exception:
            self._yanit(500, {"error": "sunucu_hatasi"})
            o.bitir("hata")
            raise
        self._yanit(200, {"report": {k: rapor[k] for k in ("added", "updated", "deleted", "skipped")}})
        o.bitir("birlestirildi", rapor)


class WifiYonetici:
    """Uygulama başına TEK eşleştirme oturumunu tutar (ui katmanı bunu sarar).

    Yeni `baslat` eskisini (varsa) kapatır: iki oturum aynı anda olmaz ve sayfası
    yenilenen kullanıcı 3 dakika kilitli kalmaz.
    """

    def __init__(
        self,
        *,
        depo_ac: Callable[[], AbstractContextManager[Repo]],
        cihaz_adi: str,
        cihaz_id: str,
        uygulama: str,
        ip_bul: Callable[[], str] = varsayilan_ip_bul,
        zaman: Callable[[], float] = time.monotonic,
        gunluk: Callable[[str], None] = _yaz,
        test_ipleri: frozenset[str] = frozenset(),
    ) -> None:
        self._ayar = {
            "depo_ac": depo_ac, "cihaz_adi": cihaz_adi, "cihaz_id": cihaz_id,
            "uygulama": uygulama, "zaman": zaman, "gunluk": gunluk, "test_ipleri": test_ipleri,
        }
        self._ip_bul = ip_bul
        self._kilit = threading.Lock()
        self._oturum: WifiOturumu | None = None

    def baslat(self) -> dict:
        """Yeni oturum açar. Bağlantı (token içerir) YALNIZ burada döner."""
        with self._kilit:
            if self._oturum is not None:
                self._oturum.iptal()
            ip = self._ip_bul()
            oturum = WifiOturumu(ip=ip, **self._ayar)  # type: ignore[arg-type]
            try:
                oturum.baslat()
            except ImportError:  # `cryptography` yok: kurulum eksik, ama uygulama ayakta kalsın
                raise WifiHatasi("wifi_baslatilamadi", "eşleştirme sunucusu başlatılamadı") from None
            self._oturum = oturum
        return {
            "baglanti": oturum.baglanti,
            "ip": oturum.ip,
            "port": oturum.port,
            "ad": oturum.cihaz_adi,
            "parmak_izi": oturum.parmak_izi,
            **oturum.durum(),
        }

    def durum(self) -> dict:
        """Son oturumun durumu; hiç açılmadıysa `{"asama": "yok"}`."""
        oturum = self._oturum
        return oturum.durum() if oturum is not None else {"asama": "yok"}

    def iptal(self) -> None:
        if self._oturum is not None:
            self._oturum.iptal()

    def karar(self, onay: bool) -> None:
        """Birleştir (True) / Reddet (False); bekleyen karar yoksa `WifiHatasi`."""
        if self._oturum is None:
            raise WifiHatasi("wifi_karar_yok", "bekleyen bir karar yok")
        self._oturum.karar_ver(onay)

    def kapat(self) -> None:
        """Uygulama kapanırken: açık oturum varsa kapatır."""
        if self._oturum is not None:
            self._oturum.bitir("kapandi")
