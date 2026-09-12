# طراحی messaging و projection

این بخش مرجع تصمیم‌های فعلی است و جایگزین پیشنهادهای قبلیِ ناسازگار می‌شود.
پیوست انگلیسی انتهای فایل فقط شواهد تاریخی است، نه برنامهٔ اجرای فعلی.
پیشنهاد دستیار بدون پذیرش کاربر تصمیم نهایی نیست. تغییر تصمیم باید همراه
دلیل و اثر آن ثبت شود؛ محدودیت تازه نباید بی‌صدا به ابزار تحمیل شود.

## ۱. وضعیت فعلی و محدودهٔ کار

- هفت کلاس پایهٔ projection، patch، حذف، نسخه‌های دسته‌ای و fanout در
  `fastamu/messaging/projections/` وجود دارند؛ خروجی bulk نیز تعریف شده است.
- پیاده‌سازی قبلی messaging، outbox/inbox و retry سفارشی حذف شده است.
- `AbstractConvertor` پیاده شده است. طبق تصمیم جدید، `SyncProjection`،
  قرارداد `get_ids()` و decoratorِ `sync` حذف شدند؛ ترمیم از batch موجود با ID
  ورودی استفاده می‌کند. خواندن شکست‌ها و گروه‌بندی بیرون projection است.
- گام ۲ پیاده شده: کلاس Register و نمونهٔ مشترک آن در
  `tasks/projection/delivery/register.py`، metadata صف و کشف کلاس‌ها با
  `Bootstrapper.boot_projections()`. ساخت task و اتصال Dishka متدهای protected
  همین کلاس‌اند؛ Register عمومی و فایل registration جدا نداریم.
- گام ۳ پیاده شده: decoratorهای انتشار در `tasks/projection/delivery/decorators.py` و
  broker/entry point مستقل در `tasks/projection/broker.py`.
- گام ۴ پیاده شده: RetryPolicy اختیاری، SmartRetry بومی و scheduler مستقل Redis.
  تسک دوره‌ای ترمیم و مخزن اختیاری SQL نیز مطابق بخش‌های ۸ و ۹ پیاده شدند.
- SQL transaction، UoW، repositoryهای DB/ES و job/scheduler موجود حفظ می‌شوند.
- گام ۱ با ۲۹ تست projection و بررسی Ruff/Pyright تأیید شده است؛ این تست‌ها
  اتصال واقعی DB/ES یا broker را اثبات نمی‌کنند. مراحل بعدی فقط Fastamu را
  پله‌پله تغییر می‌دهند.
  هماهنگ‌کردن Goldis مرحلهٔ جداست. هیچ issue با نوشتن این سند بسته نمی‌شود.

## ۲. سه بخش اجرایی مستقل

| بخش | اجرا | مسئولیت |
| --- | --- | --- |
| Jobs | scheduler و worker مجزا | scheduler موعد اجرا را تعیین می‌کند؛ worker کار زمان‌بندی‌شده را انجام می‌دهد |
| Projection | worker/process مستقل | اجرای درخواست مشخص برای ساخت، patch یا حذف read model |
| Events | runtime و مصرف‌کننده‌های مستقل | دریافت اتفاقی مانند خرید و اجرای handlerهای مربوط |

هر runtime اجرایی container، عمر اتصال‌ها و poolهای خودش را دارد. instance
دارای session بین processها یا پیام‌های هم‌زمان به اشتراک گذاشته نمی‌شود.
اشتراک سرور DB/ES به معنی اشتراک container یا worker نیست؛ ظرفیت سرور همچنان
می‌تواند میان این processها مشترک باشد.

در event، handlerهای متفاوت ممکن است هرکدام یک رویداد را دریافت کنند؛ در
projection، نام task مشخص می‌کند کدام عملیات اجرا شود. این دو مدل ثبت و صف‌بندی
نباید به یک dispatcher عمومی تبدیل شوند. طراحی event در این مرحله بازنویسی نمی‌شود.

scheduler زمان اجرای تسک ترمیم را تعیین می‌کند. تسک ترمیم شکست‌ها را می‌خواند
و گروه‌بندی می‌کند؛ درخواست‌های batch در worker مستقل projection اجرا می‌شوند.
process زمان‌بند عملیات DB/ES projection را اجرا نمی‌کند.

## ۳. لایه‌ها و محل مسئولیت‌ها

| بخش | مسئولیت |
| --- | --- |
| `infra` | اتصال‌ها، repository و دسترسی فنی به DB/ES و منابع خارجی |
| `core` | تنظیمات؛ bootstrapper موجود ابزار کشف اجزاست |
| منطق برنامه | پیاده‌سازی projection، قواعد نوشتن، قواعد انتخاب ID برای ترمیم و تبدیل داده |
| `messaging/projections` | کلاس‌ها و قراردادهای قابل استفادهٔ projection، convertor و RetryPolicy |
| `tasks` | entry pointها (`broker`/`scheduler`)؛ `delivery`: Register و نمونهٔ مشترک آن، ساخت wrapper، انتشار و لیبل‌ها؛ `repair`: هدف‌های ترمیم و middleware ثبت شکست |
| `web` و entry pointها | اتصال اجزای runtime و راه‌اندازی/بستن منابع لازم |

projection منطق برنامه است؛ پیاده‌سازی‌های محصول و تنوع در لایهٔ `app` برنامه
قرار می‌گیرند، نه صرفاً به دلیل استفاده از ES در `infra`. پایه‌های framework
زیر `fastamu.messaging` باقی می‌مانند؛ بستهٔ موازی `fastamu.projections` نمی‌سازیم.

کلاس projection نباید broker یا entry point داخل `tasks` را import کند. metadata
مانند `queue_name` و policy، instance زندهٔ broker یا container نیست. کشف ماژول
از مسیرهای قراردادی bootstrapper مجاز است؛ import پویا برای پیدا کردن broker
یا پوشاندن وابستگی برگشتی اضافه نمی‌شود. تغییر نام کلی `common` در این کار نیست.

decorator انتشار در `tasks/projection/delivery/decorators.py` singleton همان بخش را
مصرف می‌کند. در کلاس‌های `messaging` وابستگی برگشتی به `tasks` ایجاد نشده است.

## ۴. ابزارهای projection

| ابزار | ورودی | اجرا |
| --- | --- | --- |
| `AbstractProjection` | یک ID | خواندن، تبدیل، نوشتن یک سند |
| `AbstractPatchProjection` | یک ID | خواندن، ساخت patch، نوشتن فیلدهای تعیین‌شده |
| `AbstractUnProjection` | یک ID | حذف مقصد بدون خواندن و تبدیل اجباری |
| `AbstractBatchProjection` | چند ID | خواندن گروهی، تبدیل، نوشتن گروهی |
| `AbstractBatchPatchProjection` | چند ID | ساخت و نوشتن patchهای گروهی با حفظ ارتباط ID و patch |
| `AbstractBatchUnProjection` | چند ID | حذف گروهی |
| `AbstractFanoutProjection` | یک ID مبدأ | خواندن و ساخت چند سند مقصد |
| `AbstractConvertor` | مدل مبدأ | تبدیل همگام به نوع مقصد، بدون I/O |

کلاس‌ها رفتار فعلیِ خواندن، تبدیل و نوشتن را حفظ می‌کنند. batch با حلقهٔ ارسال
تسک تکی پیاده نمی‌شود؛ یک درخواست batch و یک مسیر نوشتن گروهی دارد. fanout نیز
با batch ورودی یکسان ندارد. ورودی خالیِ batch هیچ I/O مقصدی انجام نمی‌دهد.

`AbstractConvertor` یک کلاس انتزاعی با `convert(model) -> destination` و type
hint مبدأ/مقصد است. برای استفادهٔ مجدد از تبدیل، پیاده‌سازی projection می‌تواند
آن را با DI دریافت و در `_convert` فراخوانی کند. اضافه‌شدن این ابزار، مجوز
تحمیل constructor یکسان یا حذف همهٔ `_convert`های موجود نیست.

برنامه نوع نوشتن را تعیین می‌کند: create-only، جایگزینی کامل، patch یا delete.
patch فیلدهای تعیین‌شده را نگه می‌دارد، از جمله `None` صریح؛ حذف فیلدهای unset
با `exclude_unset=True` با حذف همهٔ مقادیر None یکسان نیست. upsert، رفتار سند
ناموجود، conflict، کنترل نسخه و قفل به همهٔ projectionها تحمیل نمی‌شوند.

`BulkItemResult` نتیجهٔ هر عملیات مقصد را حفظ می‌کند. ID مقصد الزاماً ID مبدأ
نیست، مخصوصاً در fanout. شکست جزئی نباید در اتصال task به موفقیت کامل تبدیل
شود. نحوهٔ گزارش آن به middleware و انتخاب ID برای ترمیم باید پیش از آن مرحله
تعیین و تست شود. repositoryهای bulk فعلی که شمارش برمی‌گردانند هنوز adapter
این قرارداد را ندارند.

## ۵. Register و کشف خودکار

یک کلاس به نام `Register` داخل `tasks/projection` و یک نمونهٔ مشترک از آن داریم. دادهٔ
اصلی آن فقط یک dict است:

```text
کلاس concreteِ projection → task ساخته‌شده با broker.task
```

نمونهٔ مشترک یعنی یک نمونه در هر process برنامه؛ dict حافظهٔ مشترک بین processها
نیست. producer و worker تعریف‌های سازگار را هنگام startup ثبت می‌کنند.

مسئولیت‌ها:

1. bootstrapper کلاس‌های concrete را از `app/projections.py` یا فایل‌های مستقیم
   packageِ `app/projections/` کشف می‌کند. تعریف‌های `__init__.py` نیز دیده
   می‌شوند؛ subpackageهای تو‌در‌تو در این مرحله اسکن نمی‌شوند. کلاس abstract،
   کلاس import‌شده و alias تکراری دوباره ثبت نمی‌شوند.
2. `Register.register(projection, broker)` با متد protectedِ
   `_register_projection` ساخت task را انجام می‌دهد. `_single` و `_batch`
   متدهای protected همین کلاس‌اند و wrapper با DI آماده می‌سازند.
3. task با `broker.task`، نام یکتا و `queue_name` کلاس ساخته می‌شود.
   labelهای RetryPolicy نیز در گام ۴ اضافه شده‌اند.
4. task ساخته‌شده در dict همان instance نگه داشته می‌شود؛
   `Register.get(projection)` همان task را برمی‌گرداند.
5. caller task را از dict می‌گیرد و با `kiq(...)` درخواست اجرا می‌فرستد.

نام صف مقصد ارسال است؛ نام task تعیین می‌کند چه عملیاتی اجرا شود. چند کلاس
می‌توانند `queue_name` یکسان داشته باشند. مثلاً تمام نویسندگان سند محصول در صف
products قرار می‌گیرند، حتی اگر مبدأ دادهٔ یکی از آن‌ها تنوع باشد. صف مربوط به
سند مستقل تنوع می‌تواند جدا باشد. این گروه‌بندی را برنامه روی کلاس مشخص می‌کند.

تمام رفتار ثبت projection در یک کلاس و یک فایل داخل `tasks/projection` است؛
helperهای ساخت task تابع آزاد بیرون کلاس نیستند. broker به register داده می‌شود؛
این کلاس اتصال broker، scheduler یا ذخیره‌ساز شکست نمی‌سازد. برای هر projection
decorator ثبت یا تابع task دستی لازم نیست و registry دوم هم نمی‌سازیم.

نام task فعلی از `module:qualname` کلاس ساخته می‌شود. تغییر نام یا مسیر کلاس
این نام را عوض می‌کند؛ نام پایدار مستقل برای مهاجرت پیام‌های قدیمی هنوز API
جدا ندارد. queue_name باید رشتهٔ غیرخالی باشد؛ broker واقعی باید صف‌های متناظر
را نیز تنظیم کند. مقدار label به‌تنهایی اثبات routing نیست.

در گام ۳، wrapper با دیدن نتیجهٔ ناموفق bulk، `ProjectionBatchError` می‌دهد؛
همهٔ نتایج در `error.results` حفظ می‌شوند. فراخوانی مستقیم کلاس‌های projection
همچنان نتیجهٔ bulk را برمی‌گرداند. این رفتار به‌تنهایی retry یا ذخیرهٔ شکست را فعال نمی‌کند؛ retry policy لازم دارد.

در worker، Dishka وابستگی‌های instance را در scope همان اجرای پیام تأمین می‌کند.
ثبت کلاس جای provider وابستگی‌های آن نیست. producer برای `kiq` به ساخت instance
projection یا بازکردن اتصال DB آن نیاز ندارد. تعارض نام، ثبت یک کلاس روی broker
متفاوت و دریافت کلاس ثبت‌نشده باید رفتار صریح داشته باشند؛ overwrite بی‌صدا نکنیم.

## ۶. decorator project

پیاده‌سازی در `tasks/projection/delivery/decorators.py` است و مستقیماً از Register همین
بخش استفاده می‌کند؛ کلاس‌های منطق projection به لایهٔ tasks وابسته نشده‌اند.

قرارداد آن مستقل از SQL transaction است:

1. تابع را اجرا کند.
2. پس از برگشت موفق، ورودی projection را با mapper/lambda بسازد.
3. درخواست اجرای task مربوط را منتشر کند.
4. خروجی اصلی تابع را برگرداند.

`project` نه commit می‌زند، نه rollback می‌کند، نه scope تراکنش را بررسی می‌کند
و نه فراخوانی تودرتو را بر اساس وضعیت تراکنش رد می‌کند. در شکست تابع، انتشار
انجام نمی‌شود. خطای mapper یا انتشار مخفی نمی‌شود و decorator مدعی rollback
عملیات قبلی نیست. `project`، `patch`، `unproject` و `fanout` قرارداد انتشار تکی
مشترک دارند و lambda یک ID برمی‌گرداند؛ کلاس ثبت‌شده نوع عملیات را تعیین می‌کند.
نسخه‌های `batch_project`، `batch_patch` و `batch_unproject` یک پیام با لیست ID
می‌فرستند. decorator مخصوص Sync نداریم؛ iterableبودن خروجی مبنای حدس نوع عملیات نیست.
اعتبارسنجی ID با Pydantic است؛ bool و رشتهٔ عددی به‌عنوان ID پذیرفته نمی‌شوند.

```python
@project(...)  # نمونهٔ ترکیب، نه API پیاده‌شده
@transactional
async def update_product(...):
    ...
```

اگر transactional مالک commit باشد، این ترکیب پس از commit منتشر می‌کند.
اگر تابع به تراکنش بزرگ‌تری ملحق شده باشد، بازگشتش به معنی commit نهایی نیست؛
برنامه انتشار را در مرز مناسب قرار می‌دهد. این واقعیت مجوز اضافه‌کردن guard،
buffer یا dispatcher به decoratorها نیست. transactional فقط تراکنش و UoW فقط
عمر session و عملیات commit/rollback را مدیریت می‌کنند.

## ۷. RetryPolicy روی خود projection — پیاده شد

هر projection یک `retry_policy: ClassVar[RetryPolicy | None]` دارد؛ پیش‌فرض
`None` است. policy در `messaging/projections/policies.py` فقط دادهٔ معتبر Pydantic
است و runtime یا settings را import نمی‌کند.

```python
retry_policy: ClassVar[RetryPolicy | None] = RetryPolicy(
    max_attempts=3, delay=5,
)
```

- `max_attempts` تعداد کل تلاش‌ها، شامل اجرای اول است؛ `1` یعنی بدون تکرار.
- `delay` فاصلهٔ ثابت غیرمنفی و متناهی به ثانیه است. ارسال اول تأخیر ندارد؛
  polling زمان‌بند و بار worker می‌توانند اجرای retry را دیرتر کنند.
- Register این مقادیر را به `retry_on_error`، `max_retries` و
  `projection_retry_delay` تبدیل می‌کند. `max_retries` در Taskiq 0.12.1
  با وجود نامش تعداد کل تلاش‌ها را محدود می‌کند. بدون policy، labelِ
  `retry_on_error=False` صریحاً ثبت می‌شود.
- `RetryLabelsMiddleware` فقط هنگام اجرا `delay` را برای SmartRetry می‌گذارد
  و هنگام ارسال حذف می‌کند؛ چون RabbitMQ نیز همین label را برای تأخیر حمل
  می‌خواند. شمارنده، محاسبهٔ زمان، شناسهٔ ثابت و ایجاد retry کار SmartRetry است.
- jitter، backoff و فیلتر exception در نسخهٔ فعلی تنظیمات کلی middleware هستند؛
  به‌عنوان گزینهٔ مستقل هر کلاس عرضه نشده‌اند. فیلد پشتیبانی‌نشده رد می‌شود.
- هر تلاش DI scope تازه دارد؛ scope شکست‌خورده پیش از ذخیرهٔ retry بسته می‌شود.
  decoratorهای انتشار و transactional تغییری نمی‌کنند.

با تأیید کاربر، تأخیر به `ListRedisScheduleSource` بومی و process زمان‌بند
مستقل projection سپرده شد. صف delay مشترک taskiq-aio-pika 0.6.0 مقصد retry
چند صف را حفظ نمی‌کند؛ broker سفارشی یا وابستگی به plugin اضافه نکردیم.
`tasks.projection.retry` شامل URL، prefix، سقف اتصال، اندازهٔ خواندن و timeout
است. بدون این تنظیم source ساخته نمی‌شود؛ داشتن policy بدون تنظیم زیرساخت
در startup خطا می‌دهد. extraِ projection اکنون taskiq-redis را هم نصب می‌کند.

```bash
taskiq scheduler fastamu.tasks.projection.scheduler:scheduler --update-interval 1
```

برای هر prefix فقط یک scheduler اجرا می‌شود؛ Redis 6.2+ و prefix مستقل برای
هر برنامه/محیط لازم است. prefix نباید `:` داشته باشد، مطابق parser بومی.
worker و scheduler تنظیمات یکسان دارند؛ scheduler container برنامه نمی‌سازد.
صف، task ID و ورودی retry حفظ می‌شوند. scheduler خاموش باشد، retryهای با موفقیت
ثبت‌شده تا راه‌اندازی آن در Redis می‌مانند، با دوام متناسب با تنظیمات Redis.

حدود همین پیاده‌سازی:

- retry کل task را با IDهای قبلی تکرار می‌کند؛ آیتم موفق batch ممکن است تکرار
  شود. replay دقیقاً آیتم‌های ناموفق این مرحله نیست.
- پایان تلاش‌ها فقط خطای Taskiq است؛ ذخیرهٔ آن فقط با فعال‌بودن نگاشت repair انجام می‌شود.
- در ack پیش‌فرض `when_saved`، خطای ذخیرهٔ retry منتشر می‌شود و پیام Rabbit
  ack نمی‌شود؛ آزادشدن delivery/channel برای redelivery لازم است. صرف برگشت
  Redis باعث تلاش فوری دوبارهٔ همان delivery نمی‌شود.
- source بومی نوشتن داده و index زمان را در دو دستور انجام می‌دهد؛ نوشتن اتمیک
  و تضمین عدم گم‌شدن مسیر Rabbit/Redis نداریم. scheduler نیز leader election
  ندارد و چند instance می‌توانند پیام تکراری بفرستند.
- Taskiq 0.12.1 زمان‌بندی ناموفق در ارسال را در حافظه attempted ثبت می‌کند؛
  retry زمان‌بندی باقی‌مانده در Redis ممکن است restart scheduler بخواهد.
- ListRedisScheduleSource 1.2.1 با بازیابی زمان‌های گذشته، هر refresh فضای کلید
  Redis را scan می‌کند. Redis با فضای کلید کوچک و interval متناسب لازم است؛
  buffer_size سقف خواندن است، نه تعداد کار همزمان. pool آن نسخه در shutdown
  خود source بسته نمی‌شود؛ lifecycle broker آن را می‌بندد.

تست واقعی با RabbitMQ و Redis موقت، producer/worker/scheduler جدا، دو صف،
شروع دیرهنگام scheduler، بررسی خود صف مقصد، فاصلهٔ retry، حفظ task ID، پایان
تلاش‌ها و توقف پس از موفقیت انجام شد. تست واحد قطع Redis، ack نشدن پیام و
بسته‌شدن scope را نیز بررسی می‌کند. این تست‌ها تضمین exactly-once نمی‌دهند.

اعتبارسنجی نهایی گام ۴: ۱۹۳ تست پاس شد؛ ۲ تست اتصال PostgreSQL/MySQL به‌علت
نبود تنظیم محیط skip شدند. Ruff و Pyright فایل‌های این گام بدون خطا بودند.
RabbitMQ و Redis موقت پس از تست حذف شدند؛ Goldis تغییری نکرد.

## ۸. ترمیم دوره‌ای با BatchProjection موجود — پیاده شد

تصمیم جدید جایگزین طراحی SyncProjection است. کلاس جدا، get_ids روی projection،
decoratorِ sync و SchedulerPolicy روی کلاس projection نداریم. projection فقط
IDهای داده‌شده را می‌گیرد و عملیات خودش را اجرا می‌کند.

روند پیاده‌شده با فعال‌سازی `tasks.projection.repair`:

1. هر projection لیست Redis خودش را دارد، پس گروه‌بندی جداگانه لازم نیست؛
   تسک دوره‌ای از هر لیست تا `batch_size` رکورد را با یک `LPOP` برمی‌دارد،
   قدیمی‌ترین‌ها اول.
2. برنامه نگاشت صریح `projection_name → کلاس batch ترمیم‌کننده` را تعیین
   می‌کند. اسم کلاس یا صف مبنای حدس مقصد نیست؛ Register همان dict کلاس→task است.
   نگاشت نامعتبر در زمان import رد می‌شود، نه در اجرا.
3. تسک ترمیم همان batch را **خودش اجرا می‌کند** (`batch_project(ids)`)، در
   scope مستقل خودش. انتشار به صف در کار نیست، پس چیزی بر اساس «وعدهٔ ارسال»
   تسویه نمی‌شود.
4. آنچه نتیجه تسویه‌اش نکرد برمی‌گردد ته همان لیست با یک تلاش سوخته؛ رکوردی که
   تلاش‌هایش تمام شد به `:dead` می‌رود.

۵۰ گروه حداکثر تا `concurrency` تای‌شان هم‌زمان اجرا می‌شوند (پیش‌فرض ۴)، چون
گروه‌ها هیچ‌چیز مشترکی ندارند؛ سقف برای این است که یک tick به‌ازای هر projection
یک نوشتن مقصد و یک scope باز نکند.
یک projection تکی ممکن است به batch بازسازی، patch یا حذف نگاشت شود؛ انتخاب
برنامه باید با semantics عملیات سازگار باشد. IDهای گروه‌های مختلف مستقل‌اند.

زمان‌بندی و سقف خواندن مربوط به تسک ترمیم‌اند، نه قرارداد batch. اجرای دستی
batch با لیست ID همان مسیر موجود Register را دارد. خواندن شکست در `Repair.run()` و زمان‌بندی با `LabelScheduleSource` انجام
می‌شود؛ scheduler مستقل projection هم tick ترمیم را منتشر می‌کند و هم در صورت
فعال‌بودن retry، زمان‌بندی Redis را. worker projection تسک ترمیم و batchها را
اجرا می‌کند؛ خود process زمان‌بند DB/ES را نمی‌خواند. registry تسک دیگری نداریم.

ترمیم با ID بازسازی از وضعیت فعلی منبع است. replay یک عملیات وابسته به payload
قدیمی، مانند افزایش مبلغ، از روی ID به‌تنهایی ممکن نیست؛ آن را خودکار به
بازسازی batch تبدیل نمی‌کنیم.

## ۹. middleware و مخزن اختیاری شکست — پیاده شد

پیاده‌سازی آماده، جدول در همان دیتابیس برنامه است؛ قرارداد projection به
جدول وابسته نمی‌شود. پیاده‌سازی انتخابی storage می‌تواند متفاوت باشد. middleware
شکست نهایی اجرای پیام رسیده به worker را ثبت می‌کند؛ پیام هرگز منتشرنشده خارج
از این دامنه است. مقایسهٔ منبع اصلی برای کشف عقب‌ماندگی مسیر انتخابی جداست.

```text
خطای نهایی projection → middleware انتخابی → ثبت شکست
تسک دوره‌ای ترمیم → خواندن محدود → گروه‌بندی بر اساس projection_name
                 → نگاشت صریح به batch → kiq(ids) → worker projection
نتیجهٔ موفق → رفع مشروط شکست همان رکورد؛ نتیجهٔ ناموفق → باقی‌ماندن رکورد
```

پیاده‌سازی:

- `messaging/projections/repair/records.py`: قرارداد FailureStore با سه عمل
  (`record`/`take`/`requeue`) و رکورد صف. `repair/queue.py` آن را روی list‌های
  Redis پیاده می‌کند — همان کلاینت مشترک برنامه، بدون جدول و بدون مهاجرت.
  دلیل Redis: شکست باید وقتی ثبت شود که مسیر نوشتن دیتابیس خودش خراب است.
- `messaging/projections/repair/settlement.py`: قاعدهٔ خالص تسویه. ورودی رزروها و
  نتایج آیتمی، خروجی «چه رفع شود و چه برگردد». بدون taskiq و بدون DB تست می‌شود.
- `messaging/projections/repair/orchestration.py`: Repair فقط رزرو، گروه‌بندی و
  سپردن هر گروه به `RepairPublisher` را انجام می‌دهد؛ transport را نمی‌شناسد.
- `tasks/projection/publisher.py`: پیاده‌سازی taskiq همان Protocol. bind فقط
  نام‌های ثبت‌شده و batch بودن مقصد را اعتبارسنجی می‌کند.
- `tasks/projection/middlewares/failures.py`: آداپتور نازک — receipt را می‌خواند،
  قاعدهٔ تسویه را صدا می‌زند و به store می‌سپارد. پیش از SmartRetry و Dishka نصب
  می‌شود؛ اجرای معکوس on_error ابتدا scope را می‌بندد، سپس retry را تصمیم
  می‌گیرد و در پایان شکست نهایی را ثبت می‌کند.
- `tasks/projection/labels.py`: نام لیبل‌های taskiq در یک جا، تا رشتهٔ جادویی در
  register و middleware تکرار نشود.
- ترمیم **اجرا** می‌کند، منتشر نمی‌کند: `Repair.run()` از هر لیست تا `batch_size`
  برمی‌دارد، batch هدف را خودش صدا می‌زند و آنچه تسویه نشد را برمی‌گرداند ته صف.
  چون `take` همان pop است، دو اجرای هم‌پوشان یک رکورد نمی‌گیرند؛ پس توکن رزرو،
  lease و receipt حذف شدند. بهایش: مرگ پروسه بین take و requeue آن دسته را
  می‌برد.
- سقف تلاش روی خود رکورد است: هر بازگشت یک تلاش می‌سوزاند و با تمام‌شدن
  `max_attempts` رکورد به لیست `:dead` می‌رود با لاگ هشدار — نه تکرار ابدی و نه
  دور ریختن بی‌صدا. `max_pending` سقف طول لیست و `concurrency` سقف موازی‌بودن
  گروه‌ها است.
- تفسیر کد وضعیت کار framework نیست: نویسندهٔ bulk با `final=True` می‌گوید تکرار
  این آیتم کمکی نمی‌کند، و `settled` یعنی `succeeded or final`. پس تعارض نسخهٔ
  external می‌تواند نهایی باشد و تعارض `if_seq_no` قابل تکرار بماند.
- جدول `fastamu_projection_failures` برای هر شکست UUID مستقل دارد. پیام تکراری
  ممکن است رکورد دیگری بسازد؛ IDهای یک گروه هنگام انتشار deduplicate می‌شوند.
  upsert اختصاصی dialect، حذف رکورد جدید با نتیجهٔ قدیمی و وابستگی به فایل نداریم.
- انتخاب اولیه و UPDATE شرطی جدا هستند. UPDATE با توکن رزرو، مالکیت را مشخص
  می‌کند؛ دو claimant نمی‌توانند همان رزرو معتبر را بگیرند. claim زیر رقابت
  ممکن است کمتر از limit برگرداند. تراکنش SQL هنگام kiq باز نمی‌ماند.
- receipt فشرده شامل نام مبدأ، token و نگاشت UUID رکورد→ID ورودی است. با موفقیت
  فقط رکوردهای همان token حذف می‌شوند. نتیجهٔ قدیمی پس از رزرو مجدد بی‌اثر است.
- شکست انتشار و پایان ناموفق ترمیم، رزرو را با تأخیر interval آزاد می‌کنند.
  crash با انقضای lease قابل انتخاب مجدد می‌شود. این ابزار قفل سند یا exactly-once
  نیست؛ صف طولانی یا task طولانی‌تر از lease می‌تواند تکرار اجرا ایجاد کند.
- target ترمیم باید برای هر ID ورودی نتیجه‌ای با `id=str(input_id)` بدهد؛
  نتیجهٔ گم‌شده یا متناقض رفع نمی‌شود. هنگام ثبت شکست batch مبدأ، فقط اگر مجموعهٔ
  ID نتایج دقیقاً با ورودی مطابق باشد، موارد موفق فیلتر می‌شوند؛ وگرنه همهٔ
  IDهای ورودی محافظه‌کارانه نگه داشته می‌شوند. fanout با ID ورودی ثبت می‌شود.
- خطای مخزن و رفع رکورد قبل از ACK پیش‌فرض when_saved منتشر می‌شود. نیاز به
  آزادشدن channel برای redelivery همچنان وجود دارد؛ receiver اختصاصی نداریم.

تنظیمات اختیاری repair: `targets` نگاشت نام کامل taskها، `interval` پیش‌فرض ۳۰،
`batch_size` پیش‌فرض ۱۰۰۰ و `concurrency` پیش‌فرض ۴. مقادیر مثبت اعتبارسنجی
می‌شوند. نام ناشناخته یا مقصد غیرbatch در startup رد می‌شود؛ import پویا نداریم.
بدون repair هیچ store، صف repair یا task دوره‌ای ساخته نمی‌شود. بدون RetryPolicy
شکست اول نهایی است؛ همراه آن فقط پایان SmartRetry ثبت می‌شود. فقط مبدأهای حاضر
در targets ذخیره می‌شوند. repair بدون Redis retry نیز کار می‌کند.

schema به‌صورت خودکار در worker ساخته نمی‌شود. برنامه جدول اختیاری را در
infra/tables.py با `failures.to_metadata(SQLModel.metadata)` به migration خود
اضافه می‌کند؛ نمونهٔ کامل فعال‌سازی در README آمده است. این checkout هیچ
migration روی دیتابیس Goldis اجرا نکرده است.

تست این گام: ۱۰۰۰ رکورد بین ۵۰ projection، claim همزمان، انقضای رزرو، حفظ
شکست جدید، partial repair همراه retry بومی، خطای publish/storage، نگاشت نامعتبر
و receipt هزاررکوردی پوشش داده شدند. تست RabbitMQ واقعی با worker و scheduler
جدا و بدون Redis retry نیز خطای handler→ذخیره→batch→رفع موفق را تأیید کرد.
SQL با SQLite تست شده است؛ ادعای تست همهٔ dialectها یا نوشتن واقعی ES نداریم.
مجموع بررسی نهایی: ۲۰۰ تست پاس، ۲ تست PostgreSQL/MySQL به‌علت نبود تنظیم اتصال
skip. Ruff و Pyright فایل‌های همین گام بدون خطا بودند.

## ۱۰. قابلیت‌های اختیاری و حدود مسئولیت

- outbox، inbox، مخزن شکست، retry و scheduler پیش‌شرط اجرای projection نیستند.
  این مرحله انتخاب storage یا بازگرداندن پیاده‌سازی قدیمی آن‌ها نیست.
- outbox در صورت انتخاب برای دوام قصد ارسال، باید با تغییر داده در همان
  تراکنش ثبت شود؛ وظیفه‌اش تا تحویل تأییدشده است، نه پایان اجرای مصرف‌کننده.
  انتشار بعد از commit به‌تنهایی فاصلهٔ crash تا publish را پوشش نمی‌دهد.
- inbox در صورت انتخاب می‌تواند receipt و اثر SQL را در همان تراکنش ثبت کند؛
  SQL و نوشتن ES را اتمیک نمی‌کند. outbox/inbox تضمین عدم تکرار پیام در صف نیستند.
- ترمیم مبتنی بر شکست‌های ثبت‌شده لزوماً پیام هرگز منتشرنشده یا تغییر بی‌خطای
  اشتباه را کشف نمی‌کند؛ منبع انتخاب ID در تسک ترمیم تعیین می‌کند چه مواردی پوشش داده شوند.
- قفل، کنترل نسخه و سیاست overlap ابزارهای انتخابی‌اند. قفل اجرای ترمیم به‌تنهایی
  مانع تداخل با نویسندهٔ عادی نیست. framework مالک منطق سازگاری اسناد نیست.
- prefetch و concurrency قابل تنظیم‌اند؛ prefetch=1 و اجرای ترتیبی عمومی اجباری
  نمی‌شود. صف مشترک تضمین ترتیب پایان اجرا یا جلوگیری از بازنویسی سند نیست.

## ۱۱. مسائل اجرایی باقی‌مانده

این موارد دامنهٔ تست یا تصمیم همان مرحله‌اند، نه مجوز ساخت چارچوب‌های تازه:

| مورد | مرحلهٔ رسیدگی |
| --- | --- |
| نام پایدار task و جلوگیری از برخورد wrapperها | ثبت خودکار |
| مسیر کشف و اتصال providerهای projection | bootstrap و DI |
| روش دسترسی decorator به Register بدون import برگشتی | انتشار |
| mapping دقیق RetryPolicy به label و زیرساخت تأخیر | retry |
| محل ScheduleSource و جلوگیری از انتشار تکراری schedule در چند scheduler | ترمیم دوره‌ای |
| محدودیت batch، overlap، نتیجهٔ جزئی و رفع نیاز ثبت‌شده | ترمیم و middleware |
| تعریف «اجرانشده» و ثبت اولین/آخرین شکست | middleware |
| payload خراب و task ناشناخته پیش از اجرای handler | تست واقعی transport؛ middleware به‌تنهایی حل‌شده فرض نشود |

هزینهٔ discovery و ثبت هنگام startup است. dict lookup مسیر انتشار را ساده
نگه می‌دارد؛ throughput اندازه‌گیری نشده است. هزینهٔ غالب محتمل خواندن DB،
نوشتن ES، اندازهٔ batch و ظرفیت poolهاست. worker مستقل projection با jobها
ظرفیت اجرایی مشترک ندارد، اما سرور DB/ES می‌تواند مشترک باشد.

middleware ذخیرهٔ شکست در خرابی گسترده بار نوشتن ایجاد می‌کند. خواندن شکست مبتنی
بر «فقط N ثانیهٔ اخیر» ممکن است شکست‌های قدیمی را پس از downtime جا بگذارد؛
پیاده‌سازی برنامه باید انتخاب pending/cursor و محدودیت query مناسب خود را داشته
باشد. schema، index، قفل و retention عمومی قبل از انتخاب storage نمی‌سازیم.

issueهای قبلی مربوط به retention Redis، outbox/inbox و مهاجرت scheduleها با
این طراحی حل‌شده محسوب نمی‌شوند. audit انتهای سند سابقهٔ بررسی آن‌هاست؛ وضعیت
issueهای remote در این مرحله دوباره بررسی نشده است.

## ۱۲. ترتیب پیاده‌سازی و معیار پایان هر گام

هر گام پس از تست و مرور خودش تمام می‌شود؛ گام بعد به معنی بازنویسی دوبارهٔ
گام قبل نیست. جزئیات حل‌نشدهٔ گام‌های بعدی به اولین گام اضافه نمی‌شوند.

| گام | خروجی محدود | معیار پذیرش |
| --- | --- | --- |
| ۱ — انجام شد | AbstractConvertor و پایه‌های projection | تبدیل مستقل، batch با ID ورودی، ورودی خالی، نتیجهٔ جزئی، خطا و cancellation |
| ۲ — پیاده شد | metadata صف، Register در tasks/projection، کشف با bootstrapper و DI | dict کلاس→task، label صف مشترک/مستقل، هر هفت شکل، scope تازه و cleanup در خطا با InMemoryBroker؛ routing واقعی در گام اتصال worker |
| ۳ — پیاده شد | decoratorهای انتشار و اتصال producer/worker مستقل projection | موفقیت تابع→kiq، خطای تابع→بدون ارسال، mapper و publish error آشکار، بدون بررسی transaction؛ تست واقعی RabbitMQ با producer و worker جدا |
| ۴ — پیاده شد | RetryPolicy اختیاری و SmartRetry بومی | کلاس بدون policy retry نشود، policyها مستقل باشند، شمارش/تأخیر طبق کتابخانه، scope هر تلاش بسته شود |
| ۵ — پیاده شد | تسک اختیاری ترمیم با batch موجود | خواندن محدود، گروه‌بندی projection_name، نگاشت صریح برنامه، انتشار batch و زمان‌بندی خارج از projection |
| ۶ — پیاده شد | middleware انتخابی ثبت شکست و اتصال مخزن به تسک ترمیم | تعریف دامنهٔ شکست، نتیجهٔ جزئی، خطای storage، رفع امن موارد موفق و باقی‌ماندن موارد ناموفق |
| ۷ | تست مسیر کامل و سپس هماهنگ‌کردن Goldis | startup/shutdown، cancellation، routing و middleware واقعی، نصب بسته و تست برنامهٔ مصرف‌کننده |

گام ۱ تبدیل مستقل را اضافه کرد؛ کلاس موقت Sync با تصمیم جدید حذف شد.
کلاس‌های پایهٔ قبلی در آن گام نیاز به تغییر نداشتند. در گام ۲ metadata صف و
بخش ثبت اضافه شد. گام ۳ نیز با تست RabbitMQ موقت مستقل، سه projection تکی در
دو صف و یک batch با worker جدا تأیید شد. اثر اجرای handler در SQLite موقت ثبت
شد؛ این تست ادعای تست نوشتن واقعی Elasticsearch ندارد. گام ۴ نیز مطابق بخش ۷
پیاده و تست شد؛ اتصال مخزن شکست و تسک دوره‌ای ترمیم نیز در گام‌های ۵ و ۶
انجام شد. آزمون در برنامهٔ مصرف‌کننده و هماهنگ‌کردن Goldis گام بعد است.
افزودن entry point، backend، جدول شکست و policy اجرایی جزو گام ۱ نیست.

تنظیم جدید `tasks.projection` شامل `url`، `exchange` و `prefetch` است؛ اختیاری و
مستقل از `tasks.schedulers`. نصب extraِ `projection` کتابخانهٔ taskiq-aio-pika
را فراهم می‌کند. entry point از AioPikaBroker و ORJSONSerializer آماده استفاده
می‌کند. container فقط در WORKER_STARTUP ساخته و در WORKER_SHUTDOWN بسته می‌شود؛
provider دیتابیس نیز pool ساخته‌شده را هنگام بسته‌شدن container dispose می‌کند.
ساخت صف و dead-letter topology مطابق broker بومی است؛ DLQ به معنی پیاده‌شدن
middleware نگهداری شکست یا RetryPolicy نیست.

---

# Messaging dependency audit — 2026-09-12

Status: historical dependency evidence; implementation paused. The Persian
design above is authoritative, including native retry and separate periodic
reconciliation. The superseded migration draft has been removed. No runtime
code, dependency installation, queue, database, or Goldis file was changed for
this audit.

## Decision supported by the evidence

Keep Taskiq for jobs and scheduling. Do not select a replacement for projection
delivery yet. First compare simplifying the existing Taskiq integration with
moving only projections to FastStream, against the same delivery contracts.
An easier middleware hook alone does not establish that migration is cheaper
or safer. Pure dependency-wiring fixes do not require changing transports.

## Inspection boundary and environment

Inspected Fastamu sources, Goldis core sources/tests/entry points, shared message
contracts, AI worker configuration, Dockerfiles, Compose, CI, package metadata,
and the installed implementations of Taskiq, taskiq-aio-pika, taskiq-redis,
Dishka integrations, and FastStream.

Both local environments use Taskiq 0.12.1, taskiq-aio-pika 0.6.0,
taskiq-redis 1.2.1, FastStream 0.7.5, Dishka 1.8.0, and dishka-faststream 0.7.0.
Fastamu also declares taskiq-fastapi and taskiq-dependencies. No direct
taskiq-fastapi integration use was found in the inspected application sources;
that is a dependency-cleanup candidate, not authorization to remove it.

**Goldis currently imports the editable Fastamu checkout at
`/home/pouya/w/Tools/fastamu`, despite its pyproject pin to commit 44d7019.**
Editing this checkout changes Goldis's local runtime immediately. Docker/CI
install through the declared dependency instead. Validation against an editable
checkout must not be reported as validation of the pinned artifact.

Static inventory: Goldis core declares 17 scheduled/background task functions
and 17 projection classes. Fourteen product/variant projection classes share
`product_projection_queue`; the other queues are `package_projection_queue`,
`stock_projection_queue`, and `news_projection_queue`. Counts describe checked-in
Python declarations, not observed production registrations or queue contents.

## Dependency and migration impact matrix

| Contract | Evidence | Consequence of a projection-only migration |
| --- | --- | --- |
| Task creation/publication | `tasks/projection/registry.py`, `publisher.py`: `broker.task`, `kiq`, `kicker().with_task_id` | Registration, publishing, ID propagation, return/error contract, and four operation shapes require deliberate mapping. |
| Routing/ordering | Task names are module-qualified class names; multiple handlers share each domain queue; prefetch 1 and single-active-consumer | A subscriber per class or a queue per class can change dispatch and serialization. Preserve or explicitly redesign shared-queue behavior. Retry already permits later messages to overtake a failed one. |
| SQL and DI lifetime | Projection worker uses TaskiqProvider, TaskiqMessage context, Dishka request scope; CoreProvider supplies UoW | Changing decorators/import names is insufficient. Prove fresh scope per attempt, cleanup before ACK, rollback on cancellation, and same-session inbox effects. |
| Job results and HTTP contracts | Goldis attendance report routes return Taskiq task IDs and retrieve ReportModel through JobService/result backend | Keep this Taskiq path. These jobs are not fire-and-forget projection messages. |
| Runtime schedules | Goldis calculator services create/delete ScheduledTask via ScheduleSource; asset/bubble seeders also instantiate RedisScheduleSource | Preserve schedule IDs, task names, interval/cron, labels, serialization, and every writer/reader. FastStream projection consumption does not replace scheduling. |
| Outbox recovery | `tasks/outbox/scheduler.py`: two registered Taskiq jobs, interval schedule, batch ID arguments, Dishka DB injection | Recovery remains Taskiq work even if its projection publisher changes. Job worker must have the replacement publisher available. |
| Operations dashboard | Framework and Goldis ops/jobs use AsyncResultBackend, ScheduleSource, Redis stream/group and result prefix | Changing broker construction affects DI even if public job APIs do not move. Redis retention issues remain. |
| Web startup | `web/app.py` → `tasks/lifespan.py` starts projection/job/event publishers | Web must publish without accidentally starting projection consumers or opening unnecessary backends. |
| Job worker startup | Goldis `src/run/scheduler.py` uses TaskiqEvents to build the projection registry and start projection/event publishers | Migrating only the projection worker entry point leaves job-originated projections broken. |
| Event worker startup | Goldis `src/run/signal.py` starts projection and scheduler publishers around the FastStream app | Event handlers can produce projections/jobs. Publisher lifetimes must change together with the transport. |
| Scripts/seeders | Goldis script runner and seeder entry points import/start task integrations | Include offline execution paths and failure cleanup; do not validate only web startup. |
| Packaging | Fastamu cqrs extra currently installs taskiq-aio-pika; events extra installs FastStream/Dishka integration | Projection-only installations would need revised extras. Taskiq stays required elsewhere. Test each optional-feature combination in isolation. |
| Deployment/CI | `fastamu projection-worker` runs Taskiq CLI; Goldis Compose has separate worker, scheduler, projection-worker, consumer; CI boots the stack | Entry points, worker count, signal handling, startup/shutdown, image pin, logs, and stack checks must be covered. |
| Tests | Framework queue/transaction/retry suites; Goldis captured_task_publications, tasks fixture, news outbox and product pipeline tests | Many tests intercept kick/formatter or execute Receiver directly. Rewrite transport-specific tests while retaining behavioral assertions, not merely deleting failures. |

## Persisted and wire contracts are different

- SQL outbox stores `(UUID, kind, stable target, payload)`. A news projection
  intent uses target `news.content.project` and payload `{"argument": [...]}`.
  This record is not a TaskiqMessage and can survive a transport change if the
  target resolver and payload contract stay valid.
- Once published, projection messages use Taskiq's envelope: `task_id`,
  `task_name`, `args`, `kwargs`, `labels`, and optional `labels_types`. Existing
  retry/failed queues also contain that envelope. A bare FastStream handler
  taking an integer or model is not a compatible consumer for those bytes.
- The current custom publisher copies the stable ID into RabbitMQ `message_id`
  as well as Taskiq's body. The native taskiq-aio-pika 0.6.0 publisher puts
  `task_id` in headers/body but does not explicitly set AMQP `message_id`.
  Replacing it unchanged can break identity extraction/replay assumptions.
- The custom publisher explicitly requires Basic.Ack and publishes mandatory
  through the default exchange. Native taskiq-aio-pika uses its configured
  exchange and does not perform the same explicit confirmation-result check.
  Its queue declaration also installs default DLX arguments. Neither replacement
  is automatically topology/confirmation-equivalent.
- Inbox keys are `(consumer, message_id)`. Renaming consumers or regenerating IDs
  defeats existing receipts. SQL deduplication still does not make ES/SMS effects
  atomic. The main Goldis consumers do not declare the framework inbox decorator
  or per-handler RetryPolicy in the inspected sources.
- Goldis shared signals use a separate Envelope with message_id, correlation_id,
  producer, subject, version, payload, and predeclared exchanges/DLQs. This is a
  third contract, used by AI/listeners too. Sharing RabbitMQ/FastStream does not
  justify merging it with projection or local-domain-event schemas. Its publish
  helper places identity in the envelope; it does not explicitly set AMQP
  message_id to that envelope ID.
- Replacing project json calls with orjson did not replace Taskiq's serializer:
  the inspected brokers still use its default JSONSerializer. Serialization,
  strictness, Pydantic model/date/enum conversion, labels, bytes, and exception
  behavior must be checked separately for any new publisher.

## Native-tool capability limits

Taskiq 0.12.1 parses the envelope and finds the task before pre_execute. Invalid
envelopes/unknown tasks return before middleware and ACK. pre_send is a producer
hook, not a consumer guard; direct kick/requeue paths can bypass it. Therefore
moving the current receiver guard to an ordinary middleware does not solve #1.

SmartRetryMiddleware exists and preserves task IDs. taskiq-aio-pika has native
delay-queue/plugin options. The accepted design now uses native retry settings rather than requiring
equivalence with the previous custom RetryPolicy. Terminal storage, failure
recording, and handoff guarantees still require separate verification. Installed
SmartRetryMiddleware's `use_delay_exponent` implementation multiplies delay by
retry count; do not assume the option name matches the intended backoff formula.

Taskiq also has shared_task/AsyncSharedBroker, plus an execution Context holding
the current broker. These are native options for decoupling declarations from
broker imports. The shared-task registry is global, so it must not silently
expose unrelated task/queue definitions to all workers. No adoption decision yet.

FastStream has native message ACK/NACK/reject and consumption middleware, but
NACK_ON_ERROR is redelivery, not the required bounded delayed retry policy.
Its RabbitMQ default is REJECT_ON_ERROR in the installed version; a configured
DLX determines whether rejected messages are retained. ACK explicitly acknowledges
even on ordinary errors. Neither setting can be picked as a harmless default.
Also, parser/filter failures and an unmatched handler can occur before
consume_scope; the native acknowledgement middleware has no assigned message
until consume_scope. Migration does not by itself prove that #1 disappears.

Changing queue type/arguments on an existing name can fail RabbitMQ property
equivalence checks. Inventory real queue properties and existing delayed/failed
deliveries before specifying a cutover. Do not assume an empty queue or that a
rollback can consume newly formatted messages with the old worker.

## Costs, unchanged issues, and required evidence

Three choices remain:

1. Keep Taskiq and simplify composition: lowest wire/deployment impact; receiver
   gaps still need a specific remedy. This is the baseline to compare against.
2. Move only projections to FastStream: potentially simpler native delivery
   access; changes routing, wire format, DI, all publisher lifetimes, packaging,
   and transport tests. Retry handoff and malformed-input behavior remain proof
   obligations. No performance benefit has been measured.
3. Remove Taskiq entirely: includes job results, schedules, operations APIs,
   outbox jobs, and app task declarations. Not justified by the identified
   projection-broker problem; not the recommended scope.

Issues #2/#4/#5/#7 remain separate retention/claim-concurrency/queue-isolation/
schedule-source work. #3 needs permanent-vs-transient publication handling;
#6 needs failed-message and inbox lifecycle operations. No issue is closed by
this audit, and #1 is not counted as solved by selecting a library.

Before implementation, compare both viable choices on the same tests: bad
JSON, unknown target, invalid payload/counter, two valid handlers sharing a queue,
all four projection operations, SQL commit/rollback, two simultaneous duplicates,
fresh DI scope on retry, partial ES batch failure, unavailable retry destination,
publish-confirmed-before-ACK crash, shutdown/cancellation, replay, and producer
startup from web/job/event/script entry points. Include actual message fixtures
and isolated installations, not only mocked publish calls.

Unverified by this static audit: deployed package versions, live RabbitMQ queue
arguments/plugins/policies/backlogs, persisted Redis schedules and retention,
production throughput and pool contention, and an actual alternative consumer's
behavior. No application test suite, benchmark, or live cutover was run. These
are explicit remaining evidence requirements, not assumed successes.

Sources: local files named above and installed package source;
[Taskiq brokers/shared tasks](https://taskiq-python.github.io/available-components/brokers.html),
[FastStream ACK policies](https://faststream.ag2.ai/latest/getting-started/acknowledgement/),
[RabbitMQ queue property equivalence](https://www.rabbitmq.com/docs/queues#property-equivalence).
Where documentation and installed source differ, this audit describes the
installed versions.
