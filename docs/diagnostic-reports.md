# گزارش عیب‌یابی و استخراج از سرور

این گزارش برای یافتن محل شکست سناریوی واقعی و ارائه به ایجنت اصلاح کد است.
تست fixture جای اعتبارسنجی واقعی checkout را نمی‌گیرد. پیش‌فرض همچنان
`DRY_RUN=true` و `LIVE_CHECKOUT_APPROVED=false` است؛ گزارش‌گیری این قفل‌ها را
تغییر نمی‌دهد.

## مسیر قطعی و ماندگاری

روی VPS، پروژه در `/opt/kavir-scout` مستقر شده است. مسیر **داخل کانتینر**:

```text
/app/logs/diagnostics/workflow.jsonl
/app/logs/diagnostics/workflow.jsonl.1
...
/app/logs/diagnostics/workflow.jsonl.5
```

این پوشه در volume فعلی `kavir-logs` قرار دارد؛ نام واقعی volume پیشوند پروژهٔ
Compose را دارد. به مسیرهای داخلی `/var/lib/docker` وابسته نشوید؛ دستورهای زیر
همان volume سرویس را می‌خوانند. در اجرای بدون Docker، مسیر نسبت به ریشهٔ پروژه
`logs/diagnostics/workflow.jsonl` است. فایل پس از اولین رخداد ساخته می‌شود؛
نبود آن بلافاصله پس از نصب و قبل از اجرای سناریو لزوماً خطا نیست.

هر فایل تا حدود ۵ MiB و پنج نسخهٔ قبلی نگه‌داری می‌شود؛ حدود ۳۰ MiB در مجموع.
رخداد منفرد می‌تواند اندکی از سقف فایل عبور کند. پوشهٔ diagnostics با دسترسی
۰۷۰۰ و فایل‌های جاری/چرخیده در POSIX با دسترسی ۰۶۰۰ ساخته می‌شوند. با افزایش
حجم، قدیمی‌ترین گزارش حذف می‌شود؛ پس از مشکل، گزارش را زود استخراج کنید.
برای update همان volumeها را حفظ کنید و از `docker compose down -v` استفاده
نکنید. خطای دیسک/مجوز با پیام `Diagnostic file unavailable` در کنسول اعلام
می‌شود؛ در آن وضعیت ممکن است گزارش کامل نباشد.

## چه چیزی ثبت می‌شود

- زمان دارای offset تهران و UTC، شناسهٔ اجرا و نوع اجرای روزانه/تست موجودی.
- شروع و پایان عملیات ورود، ارسال هویت/OTP، موجودی، انتخاب و checkout، با مدت اجرا.
- تغییر وضعیت، علت checkpoint دستی، نتیجهٔ نهایی و خطای cleanup/تلگرام.
- نوع exception و فایل، تابع و شماره‌خط stack؛ متن خام exception و متغیرهای محلی حذف می‌شوند.
- وضعیت ساختاری صفحهٔ فروشگاه: آماده‌بودن DOM، تعداد کارت‌ها، وجود/وضعیت
  refresh، وجود فرم OTP، نوع/نمایان‌بودن/غیرفعال‌بودن کنترل‌ها و تعداد تطبیق
  selectorهای تعریف‌شده در کد؛ همچنین مشاهدهٔ HTTP 403/429.

کد ملی، OTP، توکن، کوکی، پاسخ شبکه، متن عمومی صفحه، HTML، screenshot، مقدار
فیلدها و URL پرداخت ثبت نمی‌شوند. صفحهٔ بانک بررسی نمی‌شود. بنابراین گزارش
برای تعیین مرحله و محل شکست مناسب است؛ تغییر دقیق یک selector جدید ممکن است
همچنان به مشاهدهٔ کنترل‌شدهٔ صفحه نیاز داشته باشد. هیچ لاگ خام یا dump پروفایل
را جایگزین این گزارش نکنید.

## استخراج روی VPS

در SSH، از ریشهٔ نصب اجرا کنید:

```bash
cd /opt/kavir-scout
umask 077
mkdir -p /tmp/kavir-scout-report
docker compose cp kavir-scout:/app/logs/diagnostics/. /tmp/kavir-scout-report/
docker compose logs --no-color --since 24h > /tmp/kavir-scout-report/console.log
docker compose images > /tmp/kavir-scout-report/images.txt
tar -C /tmp -czf /tmp/kavir-scout-report.tar.gz kavir-scout-report
```

این دستورها سرویس را restart یا اجرا نمی‌کنند. کپی هنگام نوشتن ممکن است آخرین
خط ناقص داشته باشد؛ برای snapshot ثابت می‌توانید ابتدا اجرای جاری را با
`/cancel` متوقف و پایان cleanup را از `/status` تأیید کنید. یک پوشهٔ استخراج
قدیمی را برای گزارش رخداد جدید دوباره استفاده نکنید؛ نام تازه انتخاب کنید.

از دستگاه خود، آدرس و کاربر واقعی SSH را جایگزین کنید:

```bash
scp USER@SERVER:/tmp/kavir-scout-report.tar.gz .
```

فقط همین بسته را پس از بازبینی به ایجنت بدهید؛ `.env.docker`، کل volume داده،
`owner_profile.json`، پروفایل Chromium و فایل‌های قدیمی `debug/` را اضافه نکنید.
همراه گزارش، زمان مشکل به وقت تهران، آخرین پیام ربات، نتیجهٔ `/status`، نسخهٔ
کد مستقرشده و انتظار/رفتار مشاهده‌شده را شرح دهید. کد ملی و OTP لازم نیست.

## هویت و زمان‌بندی

ثبت `/start` و ویرایش `/set_national_id` مقدار هویت را در
`/app/data/owner_profile.json` ذخیره می‌کنند؛ این فایل عمداً خصوصی و خارج از
گزارش است. دفتر نوبت روزانه `/app/data/daily_start.json` و barrier مستقل سفارش
`/app/data/order_attempt.json` نیز در volume داده حفظ می‌شوند. برای رفع مشکل
ورود، فایل barrier سفارش را حذف نکنید.

برنامه مستقیماً از `ZoneInfo('Asia/Tehran')` استفاده می‌کند؛ ساعت محلی اروپا
و تغییر ساعت تابستانی اروپا در تصمیم ۰۷:۵۰ دخالت ندارند. برای تاریخ‌های بررسی‌شدهٔ
سال ۲۰۲۶، ۰۷:۵۰ تهران برابر ۰۴:۲۰ UTC است. ساعت سیستم VPS باید همگام باشد؛
نیازی به تغییر timezone سیستم به تهران نیست. برای بررسی بدون اتصال تلگرام:

```bash
docker compose run --rm --no-deps --entrypoint python kavir-scout -c 'from datetime import datetime, timezone; from kavirtire.orchestration.scheduling import TehranClock; print("UTC:", datetime.now(timezone.utc).isoformat()); print("Tehran:", TehranClock().now().isoformat())'
```

این دستور فقط زمان‌ها را چاپ می‌کند؛ bot، مرورگر یا workflow را شروع نمی‌کند.
این راهنما مسیر نسخهٔ جدید است؛ اعمال این تغییرات روی VPS و آزمون واقعی آن
باید جدا از نتیجهٔ تست‌های محلی گزارش شود.
