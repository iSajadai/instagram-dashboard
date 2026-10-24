# منابع داده (فاز ۲)

وضعیت هر منبع، از روی مستند رسمی خودش، بررسی‌شده در آبان ۱۴۰۵ (اکتبر ۲۰۲۶). کد هر آداپتور در `sajadai/providers/` است:
- `catalog.py`: منابع رسمی، ابزارهای آنالیتیکس، فایل‌ها و فرم
- `scrapers.py`: اسکرپرها
- `third_party.py`: منابعی که فعلاً «به‌زودی» هستن

## پیاده‌شده

| منبع | نوع | روش | مستند |
|---|---|---|---|
| Instagram API (ورود با اینستاگرام) | رسمی، رایگان | توکن بلندمدت ۶۰ روزه که خودکار تمدید می‌شه. دسترسی‌ها با صدا زدن endpoint هر کدوم چک می‌شه | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login |
| اپ Meta خودت | رسمی، رایگان | App ID، App Secret و توکن. تبدیل توکن: `GET graph.instagram.com/access_token?grant_type=ig_exchange_token` | https://developers.facebook.com/docs/instagram-platform/reference/access_token |
| Instagram API (ورود با فیسبوک) | رسمی، رایگان | Business Discovery برای رقبا | https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery |
| Webhooks | رسمی، رایگان | دست‌دادن با `hub.challenge` و امضای `X-Hub-Signature-256` | https://developers.facebook.com/docs/instagram-platform/webhooks |
| Metricool REST | پولی (Advanced) | هدر `X-Mc-Auth` به‌همراه `userId` و `blogId` | https://app.metricool.com/api/swagger.json |
| Metricool از راه روتین Claude | رایگان با محدودیت | مخزن git با deploy key فقط‌خواندنی؛ هر ۱۵ دقیقه چک می‌شه | — |
| Buffer | رایگان با محدودیت | GraphQL `https://api.buffer.com`. فقط آمار پست‌هایی که با خود Buffer منتشر شدن | https://developers.buffer.com/ |
| Apify | پولی (حدود ۱٫۵ تا ۲٫۷ دلار برای هر ۱۰۰۰ نتیجه) | `acts/apify~instagram-reel-scraper` و `acts/apify~instagram-profile-scraper` با `run-sync-get-dataset-items` | https://docs.apify.com/api/v2/act-run-sync-get-dataset-items-post |
| Bright Data | پولی | `datasets/v3/scrape`. پروفایل: `gd_l1vikfch901nx3by4`، ریل: `gd_lyclm20il4r5helnj` | https://docs.brightdata.com/api-reference/web-scraper-api |
| خروجی Meta Business Suite یا Professional Dashboard | دستی | CSV یا XLSX. ستون‌ها با نام‌های انگلیسی و فارسی تطبیق داده می‌شن | https://www.facebook.com/business/help/1694926080650543 |
| Download your information | دستی | ZIP یا JSON: کپشن، تاریخ و فالوئرها (آمار بازدید نداره) | https://help.instagram.com/181231772500920 |
| اسکرین‌شات Insights | دستی | مدل بینایی عددها رو می‌خونه و کاربر قبل از ذخیره تأییدشون می‌کنه | — |
| فرم دستی | دستی | لینک ریل به‌علاوهٔ عددها | — |

## «به‌زودی» (API عمومی قابل‌استفاده برای یه کریتور تنها نیست)

| منبع | دلیل |
|---|---|
| Later | API عمومی برای خوندن آمار نداره |
| Hootsuite | API برای انتشار و پیامه، نه آمار |
| Sprout Social | فقط پلن Advanced (حدود ۳۹۹ دلار برای هر نفر در ماه) |
| Iconosquare | فقط پلن‌های سازمانی (و MCP آزمایشی) |
| Agorapulse | Analytics Open API فقط در پلن Custom |
| Socialinsider | از طریق قرارداد فروش |
| RapidAPI | فروشنده‌ها مختلفن و شکل جواب ثابت نیست؛ فعلاً Apify یا Bright Data |

## مدل دادهٔ واحد و ادغام

- **مسیر داده:** هر منبع یا فایل‌های raw قدیمی رو می‌نویسه (اسکریپت‌های `fetch_*`)، یا `raw/norm/<id>.json` رو. `scripts/shape.py` همه رو با هم ادغام می‌کنه.
- **اولویت ادغام برای هر فیلد:** رسمی ← آنالیتیکس ← اسکرپر ← دستی.
- **منبع هر عدد:** در `reels[]._src` ذخیره می‌شه و تو جدول ریل‌ها با هاور دیده می‌شه.
- **اختلاف بین منبع‌ها:** اختلاف بیشتر از ۱۰٪ در `raw/discrepancies.json` ثبت می‌شه.
- **پاسخ خام:** پاسخ خام هر منبع در `raw/payloads/<id>/` نگه داشته می‌شه (۱۰ تای آخر).
- **صف همگام‌سازی:** `sajadai/jobs.py`، با بدون‌تکرار بودن کارها و backoff نمایی (۲، ۸ و ۳۲ دقیقه).
- **تلاش دوباره:** هر منبع جدا با فاصله‌های ۵، ۲۰ و ۸۰ ثانیه دوباره امتحان می‌شه، به شرطی که خطاش موقتی باشه.
- **حداقل فاصلهٔ بین اجرا:** برای اسکرپرها ۶ ساعت.
