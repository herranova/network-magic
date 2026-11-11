# Network Magic — Ağınızın büyüsü

Tamamen yerel çalışan, **ücretsiz ve açık kaynak** bir Windows ağ yönetim uygulaması. Ağınızdaki cihazları otomatik keşfeder, haritalar, internet hızınızı ölçer, dosya paylaşımı ve misafir erişimi sunar; yeni cihazları ve bağlantı sorunlarını bildirir.

Hesap, abonelik, reklam veya telemetri yoktur; verileriniz bilgisayarınızdan çıkmaz.

> Network Magic'i yalnızca kendi ağınızda veya yönetmeye yetkili olduğunuz ağlarda kullanın. Uygulama ağdaki cihazlara ping atar ve yaygın portları yoklar.

## Özellikler

| Özellik | Açıklama |
| --- | --- |
| **Ağ durum şeridi** | İnternet ⟷ Yönlendirici ⟷ Bilgisayar bağlantı zinciri, anlık ping, Wi-Fi sinyali ve tek tıkla onarım. |
| **Ağ haritası** | İnternet ve yönlendirici hiyerarşili, kategori filtreli, harita içi arama ve sürükleme/yakınlaştırma destekli kristal netliğinde etkileşimli harita. |
| **Otomatik keşif** | Ping taraması + ARP tablosu + mDNS/Bonjour + SSDP/UPnP + yaygın port taraması. Üretici adı MAC OUI veritabanından çözülür. |
| **Cihaz tanıma** | Adı bilinmeyen cihazlar için mDNS ters sorgu (telefonlar, TV kutuları), NetBIOS adı (Windows, NAS) ve web arayüzü başlığı (kamera, yazıcı, priz). |
| **Rastgele MAC eşleştirme** | Gizlilik için MAC değiştiren telefonlar aynı ad bildirirse eski kaydıyla otomatik eşleşir; gerekirse cihaz panelinden elle birleştirilir. |
| **Sorun nerede?** | Modeme (Wi-Fi/yerel ağ) ve internete (servis sağlayıcı) gecikme 10 sn'de bir ölçülür; sorunun hangi tarafta olduğu söylenir. 1 sa / 24 sa / 7 gün grafik. |
| **Kesinti geçmişi** | Her kesintinin başlangıcı, süresi ve kaynağı (sağlayıcı / yerel); erişilebilirlik yüzdesi ve servis sağlayıcıya iletilecek kopyalanabilir rapor. |
| **Telefona kurulum (PWA)** | "Ana ekrana ekle" ile kendi simgesiyle, tarayıcı çubuğu olmadan açılır. |
| **Cihaz bilgileri & Ping** | IP, MAC, üretici, ana bilgisayar adı, açık portlar, servisler ve çekmeceden anlık ICMP Ping latency testi. |
| **Hızlı işlemler** | Harita, hız testi, ağ onarımı ve dosya paylaşımına tek tıkla erişim. |
| **Yeni cihaz uyarısı** | İlk tarama bir "güvenilir taban" oluşturur. Sonradan ağa katılan cihazlar uyarı olarak listelenir. |
| **İnternet & hız testi** | Ping/jitter, indirme/yükleme hızı ve genel IP ölçümü (Cloudflare üzerinden; yedek sunucu ile). |
| **Trafik izleme** | Canlı indirme/yükleme grafiği, 1 saat / 24 saat geçmiş, toplam veri. |
| **Dosya paylaşımı** | Tarayıcıdan dosya yükleme/indirme, paylaşılan dosya listesi ve disk kullanımı. |
| **Misafir erişimi** | Süreli, tahmin edilemez bağlantı + QR kod. Misafirler yalnızca paylaşılan dosyaları indirebilir. |
| **Ebeveyn kontrolü** | Cihaz bazında yerel erişim engeli, 15/30/60/120 dk duraklatma ve haftalık saat planı. |
| **Bağlantı onarımı** | DNS temizleme, IP yenileme, ağ bağdaştırıcısını yeniden başlatma, Winsock ve TCP/IP sıfırlama. |
| **Wi-Fi & yazıcılar** | Bağlı ağ bilgisi, çevredeki ağlar ve yüklü yazıcılar. |
| **Raporlama** | Cihaz envanteri, tür/üretici dağılımı, 24 saatlik trafik özeti ve CSV dışa aktarma. |
| **Koyu / Açık Tema** | Koyu ve açık tema seçeneği, yüksek kontrast ve kolay okunabilirlik. |
| **Mobil uyumlu** | Telefonda alt sekme çubuğu, kart görünümlü listeler ve dikey ağ haritası. |

## Gereksinimler

- Windows 10/11
- Python **3.10+** (3.11 önerilir)
- Cihaz engelleme ve bazı onarım araçları için **yönetici hakları**
- İnternet erişimi (yalnızca hız testi, genel IP ve isteğe bağlı OUI güncellemesi için)

Python paketleri:

```text
Flask
psutil
qrcode
```

## Kurulum ve çalıştırma

### Kolay yol

1. Bu sayfada **Code → Download ZIP** ile projeyi indirin ve bir klasöre çıkarın.
2. **`Kur.cmd`** dosyasına çift tıklayın.

`Kur.cmd` Python 3.10+ yoksa `winget` ile kurar, proje klasöründe yalıtılmış bir Python ortamı (`.venv`) oluşturur, gerekli paketleri yükler ve uygulamayı başlatır. Sonraki açılışlarda `run.bat` yeterlidir.

### Elle kurulum

```bat
git clone https://github.com/herranova/network-magic.git
cd network-magic
python -m pip install -r requirements.txt
run.bat
```

`run.bat` yönetici değilse UAC ile yönetici olarak yeniden başlatır. Elle çalıştırmak için:

```bat
python app.py
```

Uygulama tarayıcıyı otomatik olarak `http://127.0.0.1:8765` adresinde açar. Aynı ağdaki diğer cihazlar `http://<yerel-ip>:8765` adresinden erişebilir (adres arayüzde ve konsolda gösterilir).

### Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
| --- | --- | --- |
| `NETMAGIC_PORT` | `8765` | HTTP portu |
| `NETMAGIC_HOST` | `0.0.0.0` | Dinlenen adres (`127.0.0.1` yaparak LAN erişimini kapatabilirsiniz) |
| `NETMAGIC_NO_BROWSER` | — | `1` ise tarayıcı otomatik açılmaz |
| `NETMAGIC_DATA` | `./data` | Veritabanı, paylaşılan dosyalar ve OUI dosyasının klasörü |
| `NETMAGIC_ALLOWED_HOSTS` | — | Arayüze IP yerine özel bir adla (ör. `evpc.lan`) erişecekseniz, virgülle ayrılmış izinli adlar |

## Kullanım akışı

1. İlk açılışta bilgisayarınıza bir ad verip **"Ağımı Tara ve Başla"** düğmesine basın.
2. İlk tarama, güvenilir cihaz tabanını oluşturur. Tüm cihazlar güvenilir kabul edilir.
3. Sonraki taramalarda yeni görülen cihazlar **Güvenlik & Uyarılar** ekranında ve bildirim olarak görünür.
4. Cihaz panelinden ad, tür, not ve güvenilirlik durumunu düzenleyebilir; engelleyebilir veya duraklatabilirsiniz.
5. **Ebeveyn Kontrolü** ekranından haftalık saat planı çizebilirsiniz (yeşil = izinli, kırmızı = engelli).
6. **Paylaşım** ekranından dosya yükleyip misafir bağlantısı/QR kodu oluşturabilirsiniz.

## Ağ keşfi nasıl çalışır?

1. Yerel IP, alt ağ maskesi ve varsayılan ağ geçidi okunur.
2. Alt ağdaki adreslere paralel ICMP ping atılır (64 eşzamanlı iş parçacığı).
3. `arp -a` tablosundaki MAC adresleri toplanır; ICMP'ye kapalı cihazlar da yakalanır.
4. mDNS/Bonjour sorguları ile cihaz adları ve servisler bulunur.
5. SSDP/UPnP `M-SEARCH` ile akıllı TV, yazıcı, yönlendirici gibi cihazların açıklamaları okunur.
6. Yaygın portlar taranır (22, 80, 443, 445, 515, 631, 8008, 8009, 9100, 32400 vb.).
7. MAC OUI veritabanından üretici, port/servis/ana bilgisayar adından cihaz türü tahmin edilir.

Tarama süresi tipik bir `/24` ağda **8–20 saniye** arasındadır. Tarama sırasında arayüz ilerlemeyi canlı gösterir.

### OUI / üretici veritabanı

`data/manuf`, Wireshark'ın `manuf` dosyasıdır ve yaklaşık 3 MB'tır. Dosya yoksa `netmagic/config.py` içindeki küçük yedek tablo kullanılır. Güncellemek için Wireshark deposundaki güncel `manuf` dosyasını `data/manuf` olarak kaydetmeniz yeterlidir.

## Engelleme ve güvenlik duvarı

> **Önemli sınırlama:** Engelleme, Windows Güvenlik Duvarı'na **IP adresi** bazlı kural ekler. Bu kural, hedef cihazın **bu bilgisayarla** (ve güvenlik duvarı kuralının uygulandığı makineyle) iletişimini engeller; cihazın yönlendirici üzerinden internete çıkışını **kesmez**. Tüm cihazlar için gerçek internet kısıtlaması istiyorsanız yönlendiricinin ebeveyn kontrolü / erişim kısıtlama özelliğini kullanın. Network Magic'in çalıştığı bilgisayar ağ geçidi (ICS/hotspot) olarak çalışıyorsa kural internet erişimini de etkiler.

- Engelleme, Windows Güvenlik Duvarı'na giden/gelen `block` kuralı ekler.
- Windows Güvenlik Duvarı MAC adresine göre filtreleme desteklemediği için kural IP'ye bağlıdır. Cihaz DHCP'den yeni IP alırsa bir sonraki tarama/uygulama döngüsünde kural güncellenir.
- Network Magic başlarken ve kapanırken **kendi eklediği tüm kuralları** (`NetMagic-Block-*`) siler. Böylece uygulama kapalıyken hiçbir cihaz istemeden kısıtlı kalmaz (fail-open).
- Yönetici hakları yoksa engelleme/duraklatma ve bazı onarım işlemleri nazik bir hata mesajıyla reddedilir.
- Yalnızca kendi bilgisayarınız ve yönlendirici engellenemez.

Kuralları elle temizlemek isterseniz (yönetici PowerShell):

```powershell
Get-NetFirewallRule -DisplayName 'NetMagic-Block-*' | Remove-NetFirewallRule
```

## Gizlilik

- Cihaz envanteri, uyarılar ve trafik özetleri **yalnızca bu bilgisayarda**, `data/netmagic.db` SQLite dosyasında tutulur.
- Dışarıya gönderilen tek veriler: hız testi istekleri (Cloudflare/OVH), genel IP sorgusu (ipify/ifconfig.me) ve Wireshark OUI dosyasını siz indirirseniz o indirme.
- Network Magic hiçbir paket içeriğini kaydetmez; yalnızca arayüz sayaçlarını okur.
- LAN'dan yönetim varsayılan olarak kapalıdır. Açmak için **Ayarlar → LAN'daki diğer cihazlardan yönetime izin ver** seçeneğini kullanın.

## Güvenlik modeli

Network Magic parola sormaz; güvenliği "kim, nereden bağlanıyor" üzerine kuruludur. Bilmeniz gerekenler:

- **Görüntüleme ağa açıktır.** Varsayılan olarak aynı ağdaki her cihaz `http://<yerel-ip>:8765` adresinden cihaz listesini, uyarıları ve paylaşılan dosyaları **görebilir ve indirebilir** (telefondan kullanım bunun için vardır). Misafir ağı gibi güvenmediğiniz cihazların bulunduğu ağlarda `NETMAGIC_HOST=127.0.0.1` ile yalnızca bu bilgisayardan erişime kısıtlayın.
- **Değişiklik yalnızca bu bilgisayardan yapılır.** Engelleme, onarım, ayar, dosya yükleme/silme gibi tüm yazma işlemleri, **LAN'dan yönetim** açılmadıkça yalnızca uygulamanın çalıştığı bilgisayardan kabul edilir. Misafir bağlantısının anahtarı da yalnızca yönetim yetkisi olan isteklere gösterilir.
- **Tarayıcı kaynaklı saldırılara karşı koruma.** Başka bir web sitesinin tarayıcınız üzerinden Network Magic'e komut göndermesi (CSRF) ve DNS rebinding engellenir: farklı kaynaktan gelen yazma istekleri ve tanınmayan `Host` başlıkları reddedilir.
- **Ağdan gelen adlar güvenilmez veri sayılır.** Cihazların bildirdiği adlar (mDNS, UPnP, NetBIOS, web başlığı) arayüzde kaçışlanır ve hiçbir sistem komutuna gömülmez.
- Uygulama, engelleme ve onarım araçları için **yönetici haklarıyla** çalışır. İnternete port yönlendirmesiyle **açmayın**; yalnızca yerel ağ için tasarlanmıştır.

Bir güvenlik açığı bulursanız lütfen GitHub üzerinden **Security → Report a vulnerability** ile özel olarak bildirin.

## Proje yapısı

```text
network-magic/
├─ app.py                 # Flask rotaları, tarama durumu, başlatma
├─ Kur.cmd                # Tek tıkla kurulum (Python + paketler) ve başlatma
├─ run.bat                # Windows başlatıcı (UAC ile yönetici)
├─ requirements.txt
├─ LICENSE
├─ netmagic/
│  ├─ config.py           # Sabitler, portlar, cihaz türleri, yedek OUI
│  ├─ db.py               # SQLite şema ve veri işlemleri
│  ├─ netinfo.py          # Arayüz, ağ geçidi, Wi-Fi, yazıcı, komut çalıştırma
│  ├─ discovery.py        # Ping/ARP/mDNS/SSDP/port taraması, tür tahmini
│  ├─ actions.py          # Güvenlik duvarı, onarım, hız testi, paylaşım, QR
│  └─ monitor.py          # Trafik, varlık kontrolü, kural uygulama, otomatik tarama
├─ templates/
│  ├─ index.html          # Ana tek sayfa uygulama
│  └─ guest.html          # Misafir dosya paylaşım sayfası
├─ static/
│  ├─ css/style.css
│  ├─ js/app.js
│  └─ img/favicon.svg
├─ tests/test_core.py
└─ data/                  # İlk çalıştırmada oluşur: veritabanı, paylaşılan dosyalar, OUI (depoya girmez)
```

## API (özet)

| Yöntem | Yol | Açıklama |
| --- | --- | --- |
| `GET` | `/api/status` | Ağ, trafik, sayaçlar, tarama durumu |
| `POST` | `/api/scan` | Tarama başlat (`{"deep": true, "subnet": "192.168.1.0/24"}`) |
| `GET` | `/api/scan/status` | Tarama ilerlemesi + cihazlar |
| `GET` | `/api/devices` | Cihaz listesi |
| `PATCH` | `/api/devices/<id>` | Ad, tür, not, güvenilirlik güncelle |
| `POST` | `/api/devices/<id>/block` | Engelle / engeli kaldır |
| `POST` | `/api/devices/<id>/pause` | Dakika bazında duraklat |
| `POST` | `/api/devices/<id>/schedule` | Haftalık saat planı |
| `GET` | `/api/alerts` | Uyarılar |
| `GET` | `/api/traffic` | Trafik geçmişi (`?minutes=60`) |
| `GET` | `/api/latency` | Modem/internet gecikmesi ve teşhis (`?minutes=60`) |
| `GET` | `/api/outages` | Kesinti geçmişi ve özet (`?days=30`) |
| `POST` | `/api/devices/<id>/merge` | İki kaydı aynı cihaz olarak birleştir (`{"into": <id>}`) |
| `POST` | `/api/speedtest/run` | Hız testi çalıştır |
| `GET` | `/api/wifi` | Wi-Fi durumu ve ağlar |
| `GET` | `/api/printers` | Yazıcılar |
| `POST` | `/api/repair` | Bağlantı onarımı (`flush_dns`, `renew_ip`, `restart_adapter`, `reset_winsock`, `reset_tcpip`) |
| `GET/POST` | `/api/share`, `/api/share/upload` | Dosya paylaşımı |
| `GET/POST` | `/api/guest` | Misafir erişimi ve QR |
| `GET` | `/api/report` | Özet rapor |
| `GET` | `/api/export/devices.csv` | CSV dışa aktarma |
| `PUT` | `/api/settings` | Ayarlar |

Yazma işlemleri varsayılan olarak yalnızca `127.0.0.1`/`::1` üzerinden kabul edilir; `allow_lan_control` açılırsa LAN'dan da çalışır.

## Testler

```bat
python -m unittest discover -s tests -v
```

Testler geçici bir veritabanı kullanır; gerçek Network Magic verilerinize dokunmaz. MAC normalizasyonu, alt ağ hesaplama, cihaz türü tahmini, dosya adı güvenliği, mDNS isim ayrıştırma, veritabanı işlemleri ve istek güvenliğini (CSRF, Host doğrulama, misafir anahtarı) kapsar.

## Sorun giderme

| Sorun | Çözüm |
| --- | --- |
| `Port 8765 kullanımda` | `NETMAGIC_PORT=8766` ile çalıştırın veya portu kullanan uygulamayı kapatın. |
| Cihazlar bulunamıyor | Windows Güvenlik Duvarı ICMP'yi engelliyor olabilir; yönetici olarak çalıştırın. Alt ağı **Ayarlar → Alt ağ** alanına elle girin (ör. `192.168.1.0/24`). |
| Wi-Fi ağları görünmüyor | Windows, `netsh wlan` komutları için konum izni ister. **Ayarlar → Gizlilik ve güvenlik → Konum** iznini açın. Bağlı SSID yine de profil bilgisinden gösterilir. |
| Engelleme çalışmıyor | Yönetici olarak çalıştırın. Kural IP bazlıdır ve cihazın yönlendirici internetini kesmez; yalnızca bu bilgisayarla iletişimini engeller. Cihazın IP'si değiştiyse yeniden tarayın. |
| Hız testi başarısız | Kurumsal güvenlik duvarı/proxy Cloudflare'i engelliyor olabilir. Uygulama otomatik olarak yedek indirme sunucusunu dener. |
| Uygulama kapanınca engeller kalkmıyor | Normalde kalkar; elle temizlik için yukarıdaki PowerShell komutunu kullanın. |
| Yeni cihaz uyarısı gelmiyor | **Ayarlar → Yeni cihaz bildirimleri** açık mı kontrol edin. İlk tarama taban oluşturduğu için uyarı üretmez. |

## Teknik notlar

- Tarama ve ağ komutları arayüzü kilitlememek için arka plan iş parçacıklarında çalışır.
- Windows komut çıktıları OEM kod sayfasına göre çözülür; PowerShell çıktısı UTF-8'e zorlanır.
- SQLite WAL modunda, kısa ömürlü bağlantılarla kullanılır; eşzamanlı tarama/izleme için kilitlenme önleyici `RLock` vardır.
- Trafik örnekleri 31 gün (kesinti raporundaki "izlenen süre" için), dakikalık gecikme özetleri 7 gün, kesintiler 1 yıl, okunmuş uyarılar 30 gün sonra otomatik temizlenir.
- İnternet 15 sn'de bir yoklanır; art arda iki başarısız denemede (≈5 sn arayla) kesinti başlar. Kesinti sırasında modeme ulaşılabiliyorsa sebep "servis sağlayıcı", ulaşılamıyorsa "yerel ağ / Wi-Fi" olarak kaydedilir.

### Telefona kurulum (PWA)

- **iPhone (Safari):** Paylaş → **Ana Ekrana Ekle**. Uygulama tam ekran açılır.
- **Android (Chrome):** Menü → **Ana ekrana ekle**. Chrome, tam "uygulama" kurulumu ve çevrimdışı önbellek için HTTPS ister; Network Magic yerel ağda `http://` ile çalıştığı için Android'de kısayol olarak eklenir (tarayıcı içinde açılır). Bu bilgisayarda (`http://127.0.0.1`) tam kurulum çalışır.
- Uygulama kapanırken (`/api/quit`, Ctrl+C veya süreç sonlanması) güvenlik duvarı kuralları temizlenir.

## Lisans

[MIT](LICENSE) — ücretsizdir; kullanabilir, değiştirebilir ve dağıtabilirsiniz. Yazılım "olduğu gibi" sunulur, garanti verilmez.

Bu bağımsız bir projedir; Cisco / Pure Networks'ün geçmişte aynı adla sunduğu ürünle bir bağlantısı yoktur ve o üründen kod veya görsel içermez.
