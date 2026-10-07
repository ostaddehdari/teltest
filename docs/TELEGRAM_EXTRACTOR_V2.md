# Telegram Extractor V2

Stage 08 استخراج تلگرام را از عملیات انتقال جدا و آن را به مدل `extraction_jobs` و `content_items` متصل می‌کند.

## قابلیت‌ها

- ساخت جاب فقط برای Connector تلگرام
- انتخاب Session متصل
- پذیرش Username، لینک عمومی، لینک دعوت و Source ID
- چهار روش شروع: آخرین پیام‌ها، تاریخ شمسی، Message ID و Cursor افزایشی
- Date Picker شمسی داخلی بدون وابستگی CDN
- اجرای دستی با قفل اختصاصی اکانت
- ذخیره idempotent در `content_items`
- نگهداری متن خام، نوع رسانه، مشخصات فایل و Metadata تلگرام
- ثبت ارتباط محتوا با جاب در `extraction_job_items`
- بروزرسانی Cursor با بیشترین Message ID موفق
- تاریخچه اجرا در `extraction_runs`
- حفظ کامل جاب‌ها و  محتوای مهاجرت‌داده‌شده مراحل قبل

## روش‌های شروع

| روش | رفتار |
| --- | --- |
| `all` | حداکثر تعداد تعیین‌شده از آخرین پیام‌های منبع |
| `date` | پیام‌های جدیدتر یا مساوی نیمه‌شب تاریخ شمسی در منطقه زمانی تهران |
| `message_id` | پیام‌های دارای شناسه برابر یا بزرگ‌تر از شناسه شروع |
| `incremental` | اجرای اول از آخرین پیام‌ها؛ اجراهای بعد فقط پس از Cursor ذخیره‌شده |

## API

- `GET /teltest/api/v2/telegram-extractor/meta`
- `POST /teltest/api/v2/extraction-jobs`
- `GET /teltest/api/v2/extraction-jobs/<id>`
- `POST /teltest/api/v2/extraction-jobs/<id>/run`
- `GET /teltest/api/v2/extraction-jobs/<id>/runs`
- `GET /teltest/api/v2/extraction-jobs/<id>/content`

## محدودیت مرحله

اجرای جاب در Stage 08 دستی و همگام است. پایش دوره‌ای، Cron، Retry و Backoff در Stage 10 اضافه می‌شوند. مشخصات رسانه هنگام استخراج در `media_json` ثبت می‌شود و Operations Center رسانه را هنگام انتخاب «دانلود محتوا» دریافت و Cache می‌کند.
