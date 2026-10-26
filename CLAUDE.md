# Ecosolaris Rüzgâr Paneli

Vestas V90-2.0 MW (göbek 105 m), Pojăreni, Moldova (46,893 K 28,695 D). 7 günlük rüzgâr, üretim ve gelir tahmini.
Canlı: https://sonbayofis-spec.github.io/ecosolaris-panel/ · Depo: github.com/sonbayofis-spec/ecosolaris-panel (GitHub Pages, `main`).

## Çalışma kuralları (kullanıcı kararları)
- Kullanıcı **Türkçe** konuşur. Panelde üç dil var (TR, EN, RO); metin ekleyince üçünü de ekle (`index.html` içindeki dil nesneleri).
- **Onaysız yayınlama.** Değişikliği önce yan taraftaki fark penceresinde göster; kullanıcı "yayınla/push et" demeden push etme.
- **Satış fiyatı manuel girişte kalır** (varsayılan 2,50 lei/kWh, tarayıcıda `eco_price2`). Otomatik OPEM fiyatına çevirme.
- Tasarımı bozma; kullanıcı arayüzden memnun, öncelik **verilerin doğruluğu**.

## Yapı
- `index.html`: tek dosyalık panel. Open-Meteo'dan ECMWF, ICON, GFS çeker; rüzgâr profili → rotor eşdeğer hızı → hava yoğunluğu düzeltmesi → V90 güç eğrisi → kW/MWh.
- `telegram_report.py`: saatlik Telegram raporu. **Aynı hesabı ayrıca yapar; `index.html`'deki hesapla senkron tut** (saha katsayısı, yoğunluk, net verim).
- **Veri doğrulama:** Gelen hava verisi sınırlardan geçmezse reddedilir. Python: `validate_hourly` (`telegram_report.py`, `forecast_log.py`'den de çağrılır; iş akışı kırmızı olur, bozuk rapor/kayıt üretilmez). Panel: `validApi` (`index.html`); canlı veri alınamazsa ya da doğrulanmazsa durum satırı amber olur ve kaydın yaşı yazar. Tahmin kayıtlarında (`data/forecast/*.json`) ham girdi (`raw`) ve ayarlar (`method`) vardır; geçmiş tahminler farklı katsayıyla yeniden hesaplanabilir.
- `monitor.py` + `izleme.yml`: bir iş akışı (Telegram raporu, Üretim takibi, Tahmin doğruluğu, OPEM fiyatları) başarısız olursa Telegram'a bir kez uyarı, düzelince bir kez "düzeldi" mesajı (ilk alıcıya). Tekrarlayan hatada her saat mesaj atmaz.
- `prices.py` + `fiyat.yml` → `prices.json`, `data/prices/`: OPEM PZU saatlik fiyatı (MDL/MWh), her gün 07:50 UTC (+yedek 11:30). Panel bunu yalnızca **referans** satırı olarak gösterir ("OPEM gün öncesi fiyatıyla"); satış fiyatı girişi manuel kalır. 23/25 saatlik (saat dilimi geçişi) günler atlanır.
- `accuracy.py` / `accuracy.json`: son 7 gün, 10 m rüzgâr, Kişinev havalimanı (LUKK). **Panel kartı kullanıcı isteğiyle gizli** (`SHOWACC=false` in `index.html`); iş akışı çalışmaya devam eder, istenirse tamamen kaldırılabilir.
- `forecast_log.py` → `data/forecast/`: her sabah ertesi günün saatlik tahmini (OPEM PZU teklif kapanışı 09:30'dan önce).
- `tracking.py` + `actual.csv` → `tracking.json`: tahmin ↔ gerçek üretim karşılaştırması (panel kartı veri gelince açılır). `actual.csv`: `saat,kwh` (yerel saat, kWh).
- `.github/workflows/`: `takip.yml` (06:15 UTC), `telegram.yml` (saatlik), `accuracy.yml`, `keepalive.yml`. Telegram anahtarları GitHub Secrets'ta.

## Önemli sayılar ve belirsizlikler
- Saha katsayısı **×1,14** (rüzgâr hızına). Ölçüme değil tahminlere dayanır; ±0,05 ≈ ±%14 üretim. Panel ×1,05–×1,25 senaryo aralığı da gösterir. Arazi analizi ~×1,03–1,08, Moldova atlası daha yüksek, ülke geneli kapasite faktörü düşük: çelişkili. **Gerçek üretim gelince ilk iş katsayıyı kalibre etmek.**
- Net verim %92, hava yoğunluğu saatlik (sıcaklıktan). Doğrulama şu an 10 m havalimanı verisiyle, 105 m'yi ve MWh'yi sınamıyor.
- Gerçek üretim verisi sayaç/şebeke operatöründen elle `actual.csv`'ye girilir.

## Piyasa bilgisi (kaynak: OPEM, Moldelectrica, ANRE)
- OPEM PZU saatlik, MDL/MWh. Teklifler ertesi gün için 09:30'da kapanır. Fiyat CSV: `https://www.opem.md/tranzactionare-rezultate/RezultatePZU/export/csv?Data=YYYY-MM-DD`.
- Sapma bildirilen (NF) ve ölçülen enerji farkıyla hesaplanır; sorumlu PRE. Kesin formül, tolerans, fiyat tavanı ve NF teslim saati **doğrulanmadı** (Piyasa Kuralları, ANRE HCA 283/2020).

## Açık işler
1. `Üretim takibi` ilk çalışmasını kontrol et (Actions), Telegram saatlik akışı sağlıklı mı.
2. Piyasa kurallarını doğrula (dengeleme formülü, bildirim saati).
3. `actual.csv`'ye gerçek üretim girilince katsayıyı kalibre et, aralığı daralt.
4. İstenirse Telegram raporuna da belirsizlik aralığı ekle.

## Ortam notları
- Birden çok bilgisayardan çalışılıyor: işe başlamadan önce **Fetch/Pull origin**.
- Bazı bilgisayarlarda `git push` için GitHub girişi yok; o durumda dosyalar GitHub web düzenleyicisinden yüklenebilir.
- Windows'ta betikleri yerelde denemek için Python 3.12 ve `tzdata` gerekir (GitHub Actions'ta gerekmez).
