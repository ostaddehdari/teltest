# TelTest Connector Framework v1

## هدف

Connector Framework مرز استاندارد میان منبع محتوا و هسته استخراج است. هر منبع جدید باید بدون تغییر مدل‌های `extraction_jobs` و `content_items` به این قرارداد متصل شود.

## چرخه عمر

- `stable`: پیاده‌سازی فعال و قابل انتخاب
- `beta`: پیاده‌سازی آزمایشی
- `planned`: در رجیستری ثبت شده اما هنوز قابل انتخاب نیست
- `deprecated`: در مسیر حذف کنترل‌شده

## وضعیت سلامت

- `healthy`: آماده استفاده
- `degraded`: پیاده‌سازی موجود است اما یکی از پیش‌نیازها کامل نیست
- `not_configured`: تنظیمات لازم ثبت نشده است
- `planned`: Connector هنوز پیاده‌سازی نشده است
- `failed`: بررسی سلامت با خطا پایان یافته است
- `unavailable`: منبع یا وابستگی خارجی در دسترس نیست

## قرارداد Python

هر Connector از `SourceConnector` ارث می‌برد و متد `health()` را پیاده‌سازی می‌کند. خروجی سلامت باید یک `ConnectorHealth` شامل `status`، `summary`، `details` و `checked_at` باشد.

## رجیستری فعلی

- Telegram: فعال، پایدار و قابل انتخاب
- Instagram: برنامه آینده
- YouTube: برنامه آینده
- TikTok: برنامه آینده
- Pinterest: برنامه آینده
- News Sites: برنامه آینده
- Websites: برنامه آینده
- RSS/Atom: برنامه آینده

## API

- `GET /teltest/api/v2/connectors`
- `GET /teltest/api/v2/connectors/<code>`
- `GET /teltest/api/v2/connectors/<code>/health`
- `POST /teltest/api/v2/connectors/<code>/health/refresh`

درخواست POST به نشست معتبر و CSRF Token نیاز دارد.

## اصل سازگاری

جدول `source_connectors` که در Stage 05 ساخته شد حفظ شده است. Stage 07 متادیتا و سلامت را در دو جدول جدید نگهداری می‌کند و هیچ داده‌ای از جاب‌ها یا محتواها را حذف یا تبدیل نمی‌کند.
