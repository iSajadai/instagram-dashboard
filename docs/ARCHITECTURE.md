# معماری پنل instagram.sajad.ai

خلاصهٔ کوتاه برای کسی که می‌خواد به کد دست بزنه. وضعیت ۲ آبان ۱۴۰۵ (پیش از فاز ۱ ارتقا).

## استک
- **سرور:** Python 3.12، FastAPI و uvicorn؛ یه پروسه، داخل Docker (`docker-compose.yml`، ایمیج با ffmpeg).
- **پشت nginx:** روی `creatoros-prod` در مسیر `/opt/instagram-dashboard`، با گواهی Cloudflare. محدودیت حجم آپلود فقط برای `/api/me/ig/upload` صد مگابایته.
- **دیتابیس:** SQLite در `var/panel.db`.
  - جدول `users`: هم «آدم»ها هم «پیج»ها؛ ستون `kind` نوعشون رو مشخص می‌کنه.
  - هر ردیف `prefs` (JSON ساده)، `secrets` (JSON رمزنگاری‌شده با Fernet) و `status` (وضعیت کارهای زمان‌بندی‌شده) داره.
  - جدول‌های دیگه: عضویت‌ها، تنظیمات سراسری (`settings`) و پرداخت‌ها.
  - کلید رمزنگاری: `var/secret.key` (بیرون از git).
- **فایل‌های هر پیج:** `var/users/<id>/`
  - `raw/*.json`: خروجی خام هر منبع.
  - `data/data.json`: مدل دادهٔ واحد که داشبورد می‌خونه.
  - `content/*.json`: هدف‌ها، آزمایش‌ها، موضوع‌ها، بُرد، صدای من، ایده‌ها و تحلیل، صف انتشار، قانون‌های دایرکت خودکار، لینک بایو و…
- **فرانت:**
  - `index.html` تک‌صفحه‌ایه، با d3 و ابزار داده در `assets/shim.js` (`dash.calc` و `dash.onData`).
  - روتینگ با هش (`#/reels`، `#/goals`…) در `assets/shell.js`: هر «صفحه» چند `<section>` داره.
  - صفحه‌های پنل: `panel/settings.html`، `admin.html`، `login.html`، `contact.html` و `report.html`.
  - لایهٔ طراحی: `assets/ui.css` و `assets/ui.js`.

## جریان داده
```
منبع ← scripts/fetch_*.py ← var/users/<id>/raw/*.json ← scripts/shape.py ← data/data.json ← داشبورد
```
- **اسکریپت‌ها:** هر اسکریپت `fetch_*` جدا اجرا می‌شه (`pipeline.run_script`) و env خودش رو از اتصال کاربر می‌گیره.
  - `fetch_metricool.py`: REST، پلن Advanced
  - `fetch_instagram.py`: Instagram API with Instagram Login
  - `fetch_buffer.py`
  - `fetch_discovery.py`: Business Discovery
  - `fetch_repo.py`: مخزن دادهٔ روتین Claude
- **shape.py:** همهٔ raw‌ها رو با `data.json` قبلی ادغام می‌کنه، پس تاریخچه حفظ می‌شه.
  - ریل‌ها با shortcode یکی می‌شن.
  - برای هر فیلد، Instagram API بر Metricool اولویت داره و Buffer جاهای خالی رو پر می‌کنه.
- **اتصال‌ها:** `pipeline.CONNECTIONS`. کلیدها در `secrets.connections` ذخیره می‌شن و قبل از ذخیره تست می‌شن (`test_connection`).
- **Metricool فعلی:** روتین «Sajadai dashboard data sync» در claude.ai.
  - با کانکتور Metricool هر ۶ ساعت (`29 */6 * * *` UTC) داده رو می‌خونه و در مخزن خصوصی `sajadaii/instagram` commit می‌کنه.
  - پیش از فاز ۱ پنل این مخزن رو نمی‌خوند؛ علت باگ عقب‌ماندن داده همین بود.
  - حالا اتصال «روتین Claude» هر ۱۵ دقیقه مخزن رو چک می‌کنه.

## کارهای زمان‌بندی‌شده
- همه در `pipeline.scheduler_loop` اجرا می‌شن: یه thread که هر ۶۰ ثانیه می‌چرخه، با قفل جدا برای هر پیج.
- `due_jobs` برای هر پیج تصمیم می‌گیره چی اجرا بشه:

| کار | زمان |
|---|---|
| `refresh` | هر ۶ ساعت، اگه اتصالی هست |
| `repocheck` | هر ۱۵ دقیقه، برای روتین |
| `health` | هر ساعت؛ دادهٔ قدیمی‌تر از ۸ ساعت ← زنگوله و تلگرام |
| `notify` | هر ساعت |
| `content` | شنبه‌ها ۸:۳۰ تهران |
| `igqueue` | هر دقیقه، صف انتشار |
| `igauto` | هر ۱۰ دقیقه، دایرکت خودکار |
| `agency` | اول ماه شمسی |

- بکاپ شبانه در `ops`.
- ربات تلگرام با long-poll در thread جدا اجرا می‌شه (`tgbot.loop`).

## دسترسی‌ها
- **ورود:** کوکی سشن (`session.acting_id` پیج فعلی رو نگه می‌داره).
- **نقش‌ها:** owner / editor / viewer (`need_user`، `need_editor`، `need_owner`)، به‌اضافهٔ ادمین (`need_admin`).
- **API فقط‌خواندنی و MCP:** با Bearer token هر کاربر (`/api/v1`، `/mcp`).
- **CSRF:** هر درخواست تغییر باید هدر `X-Requested-With: sajadai` داشته باشه (`same_site`).

## هوش مصنوعی
- **ai.py:** زنجیرهٔ سرویس‌های هر کاربر به ترتیب امتحان می‌شه:
  - Claude یا GPT با کلید API
  - Gemini، OpenRouter، Groq و بقیهٔ سرویس‌های سازگار با OpenAI
  - 9router
- اگه کاربر زنجیره‌ای نداشته باشه، کلید مشترک پنل استفاده می‌شه.
- **agents.py:** ۱۳ ایجنت استودیو.
- **critique.py:** نقد ویدیو.
- **insights.py:** تحلیل بعد از همگام‌سازی.

## صفحه‌های عمومی (بدون ورود)
| مسیر | صفحه |
|---|---|
| `/kit/<slug>` | مدیاکیت |
| `/l/<slug>` | لینک بایو |
| `/r/<token>` | گزارش مشتری آژانس |
| `/m/<random>` | ویدیوی انتشار، فقط تا وقتی اینستاگرام برش داره |
| `/contact` | تماس با ما |
| `/healthz` | سلامت سرویس |

## تست‌ها
- **تست‌های واحد:** `tests/test_*.py`، اجرا با `python tests/x.py`.
- **تست‌های end-to-end:** روی یه پنل موقت در پورت 18943؛ اسکریپت‌هاش بیرون از مخزنه و در گزارش هر فاز اسم برده می‌شن.
