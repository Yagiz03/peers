# TEFAS Fon Takip

[ykpfontakip.streamlit.app](https://ykpfontakip.streamlit.app)'in bir
klonu: TEFAS'taki (Türkiye Elektronik Fon Alım Satım Platformu) fonları
"peer group" (emsal grup) halinde karşılaştırmalı olarak gösteren bir
Streamlit uygulaması. Her grup için günlük getiri, seçilebilir tarih
aralığı getirisi ve YTD (yılbaşından itibaren) tablosu; her fon için de
ayrı bir detay sayfası (net giriş/çıkış, dönemsel getiriler, varlık
dağılımı) sunar.

## Neden var

TEFAS herkese açık, resmi bir API yayınlamıyor; bu uygulama, tefas.gov.tr
sitesinin kendi arayüzünün arka planda çağırdığı JSON uçlarını kullanıyor
(bkz. [Veri kaynağı](#veri-kaynağı-tefas-uçları)).

## Dosya yapısı

| Dosya | Görev |
|---|---|
| `app.py` | Streamlit arayüzü: sidebar navigasyonu, günlük/aralık/YTD tabloları, fon detay sayfası. |
| `tefas_client.py` | TEFAS uçlarını çağıran, ham yanıtları normalize eden istemci katmanı. UI'dan bağımsız, tek başına test edilebilir. |
| `config.py` | Sidebar'daki kategori/grup ağacı ve her grubun fon kodu listesi. |
| `scripts/refresh_data.py` | Günlük anlık görüntüyü (`data/*.csv`, `data/*.json`) üretir. |
| `scripts/smoke_test.py` | `tefas_client.py`'deki fonksiyonları gerçek TEFAS verisiyle test eden, CI'da (gerçek internet erişimiyle) çalıştırılan betik. |
| `.github/workflows/data-refresh.yml` | `refresh_data.py`'yi zamanlanmış olarak çalıştırıp sonucu commit+push eder. |
| `.github/workflows/tefas-smoke-test.yml` | `smoke_test.py`'yi elle tetiklenebilir şekilde çalıştırır. |
| `data/` | `refresh_data.py`'nin ürettiği anlık görüntü dosyaları (git'e commit edilir): `universe_*.csv`, `returns_*.json`, `fees_*.json`, `meta.json`, `rank_history.json`, `rank_change.json`. |

## Veri kaynağı: TEFAS uçları

TEFAS'ın `tr/fon-verileri` sayfasının kullandığı, kimlik doğrulama
gerektirmeyen JSON POST uçları:

- **`fonGnlBlgSiraliGetir`** — fon başına günlük fiyat/büyüklük/yatırımcı
  sayısı. Fon kodu boş bırakılırsa o tarih aralığındaki **tüm evreni**
  (~2000 fon) tek istekte döndürür — bu davranış, `daily_table`/`range_table`
  fonksiyonlarının grup büyüklüğünden bağımsız olarak sabit sayıda istek
  atmasını sağlıyor.
- **`dagilimSiraliGetirT`** — fon başına günlük varlık dağılımı. Fon kodu
  filtresini yok sayıp her zaman tüm evreni döndürüyor; istemci tarafında
  filtreleniyor.
- **`fonGetiriBazliBilgiGetir`** — bir fon tipindeki (YAT/EMK/BYF/GYF/GSYF)
  tüm fonlar için 1A/3A/6A/YTD/1Y/3Y/5Y getiri + risk değeri, tek istekte.
- **`fonYonetimBazliBilgiGetir`** — bir fon tipindeki tüm fonlar için
  yönetim ücreti verisi, tek istekte.
- **`fonProfilBilgiGetir`** / **`fonBilgiGetir`** — tek bir fonun profili
  (ISIN, KAP linki, komisyonlar) ve genel bilgisi (kategori, kategori
  sırası).

Her iki istek şekli de (`_post` / `_post_funds_api`, `tefas_client.py`
içinde) 429/ağ hatalarında kısa bir yeniden deneme yapar; kalıcı bir
kısıtlamada çökmek yerine boş sonuç döndürüp arayüzde "N/A" gösterir.

TEFAS, IP başına agresif bir rate-limit uyguluyor (görgül olarak, art arda
~4 istekten sonra 429/bağlantı kopması). Bu yüzden fon başına ayrı istek
atmak yerine, mümkün olan her yerde **tüm grubun/evrenin verisini tek
istekte** çekip istemci tarafında filtreliyoruz.

## Neden zamanlanmış anlık görüntü (snapshot)?

TEFAS'ın fiyatları günde bir kez (genelde akşam, piyasa kapandıktan sonra)
güncelleniyor — gün içinde değişmiyor. Buna rağmen her ziyaretçinin sayfa
yüklemesinde TEFAS'a canlı istek atmak hem gereksiz hem yukarıdaki
rate-limit'e yakalanma riskini artırıyordu.

Bunun yerine `.github/workflows/data-refresh.yml`, **her gün 09:30'da
(Türkiye saati)** `scripts/refresh_data.py`'yi çalıştırıp (geçici TEFAS
hataları betiğin içinde yeniden denenir) sonucu `data/` altına commit+push ediyor (Streamlit Cloud bu branch'i
izlediği için otomatik redeploy tetikleniyor). `app.py`'deki günlük/YTD
tabloları önce bu dosyaları okuyor; dosya yoksa (ör. ilk deploy, workflow
henüz hiç çalışmadıysa) `tefas_client.py` üzerinden canlı çekmeye
düşüyor. Fon detay sayfası ve tarih aralığı tablosu — seyrek ve tek
fon/aralık bazlı erişildiği için — canlı kalmaya devam ediyor.

## Yeni bir peer group / fon kodu eklemek

`config.py` içinde ilgili kategoriye bir `PeerGroup(...)` ekle ya da
mevcut boş bir `PeerGroup`'un `funds` listesini doldur:

```python
PeerGroup(
    "Örnek Peers",
    ["ABC", "DEF", "GHI"],
    fund_type="YAT",  # emeklilik fonuysa "EMK"
)
```

Başka hiçbir kod değişikliği gerekmez — tablolar otomatik olarak dolar.
Fon kodlarını orijinal `ykpfontakip.streamlit.app`'teki ilgili grubun
ekran görüntüsünden okuyarak ekleyebilirsin.

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

`data/` klasörü yoksa uygulama otomatik olarak canlı TEFAS isteğine
düşer; ilk anlık görüntüyü elle üretmek için:

```bash
python scripts/refresh_data.py
```

## Test

Bu depo TEFAS'a gerçek ağ erişimi gerektirdiğinden (bazı geliştirme
ortamlarında engelli olabilir), `tefas_client.py`'nin doğruluğu GitHub
Actions üzerinde gerçek veriyle doğrulanıyor:

```bash
# GitHub Actions'ta çalıştır (Actions sekmesinden "Run workflow")
.github/workflows/tefas-smoke-test.yml
```

## Sıra değişimi nasıl hesaplanıyor?

TEFAS'ın herkese açık uçlarında rütbe/sıra değişimi diye bir alan yok;
`scripts/refresh_data.py` her çalıştığında YTD getiriye göre grup içi sırayı
kendisi hesaplayıp `data/rank_history.json`'a yazıyor, bir önceki *farklı
takvim günündeki* sırayla karşılaştırıp farkı `data/rank_change.json`'a
yazıyor (aynı gün içindeki tekrar çalıştırmalar sıra değişimi saymıyor).
`app.py` bunu okuyup ▲/▼ olarak gösteriyor.

## Bilinen sınırlamalar

- **Brüt getiri** (YTD tablosundaki ilgili sütun) TEFAS'ın herkese açık
  uçlarında yer almıyor; bu yüzden "-" olarak gösteriliyor, uydurma bir
  değerle doldurulmuyor.
- Sıra değişimi, `data/rank_history.json` en az bir önceki günden veri
  içerene kadar (ilk çalıştırmadan sonraki ilk gün) "-" gösterir.
- Henüz fon kodu girilmemiş peer group'lar boş bir uyarı mesajıyla
  gösterilir (bkz. [Yeni bir peer group eklemek](#yeni-bir-peer-group-fon-kodu-eklemek)).
