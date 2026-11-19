# Metal Fabrication Management — إدارة التصنيع المعدني

`dw_manufacturing` · version **19.0.2.0.0** · Odoo **19 Community** only · LGPL-3

---

## English

### What it does

Phase 2 turns the phase-1 door and window add-on into a complete **metal fabrication**
application: estimating, bills of materials, manufacturing, quality, scrap, off-cuts,
actual costing and project profitability — for **any** fabricated metal product.

Supported out of the box (and extensible from the user interface):

steel doors · fire rated doors · windows · facades · gates · fences · handrails and
balustrades · straight and spiral staircases · canopies · light steel structures ·
shelving and platforms · sheet metal work · fully custom products.

A system administrator can add a **new product family with new dimensions, component
rules, operations and a quality template without writing a single line of code.**

### Highlights

| Area | What you get |
|---|---|
| Product families | `dw.product.family` drives dimensions, quantity method, weight method, pricing, operations, quality template and component rules |
| Quantity engine | Guided formulas built from typed terms — **no `eval`, no `safe_eval`, no user Python is ever executed** |
| Theoretical weight | Closed-form formulas for sheet, chequered plate, mesh, round/square/rectangular tube, angle, channel, I-beam, round/square/flat bar, plus manual overrides |
| Bills of materials | Item-specific BoMs with operations, sub-assemblies, customer supplied material, outsourced services and a drawing revision link; generic BoMs are never modified |
| Actual costing | Rebuilt from real stock moves, work order time, scrap, approved expenses and overhead rules — **idempotent**, protected by a unique index |
| Scrap and off-cuts | Reasons, planned/unplanned, approval, valuation, and reusable off-cuts returned to stock with standard stock moves |
| Quality | Templates per family and stage, numeric/boolean/choice/text tests, corrective actions, rework cost and a hard block on closing an MO with a failed mandatory check |
| Drawings | Revisions with attachments, release/supersede workflow, and a block on using an unreleased revision in production |
| Profitability | Item, manufacturing order, sales order, project, customer, family and period, with internal transfer value for same-entity work |
| Alerts | Eleven configurable alert types, thresholds per company and per family |
| Arabic | 100 % translated interface, RTL PDF reports with the Amiri font shipped inside the module |

### Requirements

* Odoo 19.0 Community
* Depends on `sale_management`, `mrp`, `project`, `stock_account`, `account`
* **No Enterprise application is required or referenced.**

### Install

```bash
# copy the folder into your addons path, then
./odoo-bin -c odoo.conf -d YOURDB -i dw_manufacturing --stop-after-init
```

### Upgrade from phase 1 (19.0.1.0.x)

```bash
./odoo-bin -c odoo.conf -d YOURDB -u dw_manufacturing --stop-after-init
```

Nothing is renamed and nothing is deleted. `dw.opening`, `dw.opening.component`,
`dw.component.rule`, `mrp.production.dw_*`, `sale.order.dw_*` and the
`group_dw_user` / `group_dw_manager` XML ids all keep their names, so existing
records, user assignments and attachments survive untouched.
See `docs/INSTALL.md` for the verified upgrade procedure.

### Documentation

| File | Contents |
|---|---|
| `docs/INSTALL.md` | Install, upgrade, rollback, Arabic activation, PDF prerequisites |
| `docs/USER_GUIDE_AR.md` | دليل استخدام مختصر بالعربية |
| `docs/PRODUCT_FAMILIES.md` | How to configure a new metal product family |
| `docs/FORMULA_ENGINE.md` | How the safe quantity engine works and how to build formulas |
| `docs/ACTUAL_COSTING.md` | Where every actual cost comes from and why it never duplicates |
| `docs/SCRAP_AND_OFFCUTS.md` | Scrap classification, valuation and reusable remnants |
| `docs/QUALITY.md` | Templates, checks, the mandatory gate and rework |
| `docs/PROFITABILITY.md` | Revenue recognition, internal transfers and the analysis views |
| `docs/SECURITY.md` | The eight groups and what each one may do |
| `docs/TEST_RESULTS.md` | The commands that were run and their real output |
| `docs/CHANGES.md` | Every file added or modified, plus known limitations |

### Tests

```bash
./odoo-bin -c odoo.conf -d TESTDB -i dw_manufacturing \
    --test-enable --test-tags=/dw_manufacturing --stop-after-init
```

79 tests covering the formula engine, theoretical weight, the four mandatory
acceptance scenarios, actual costing and its idempotency, scrap and off-cuts,
quality gating, profitability, access rights, multi-company isolation, drawing
control and the Arabic catalogue. Real results are recorded in
`docs/TEST_RESULTS.md`.

---

## العربية

### ما الذي تقدمه الوحدة

المرحلة الثانية تحوّل إضافة الأبواب والشبابيك إلى تطبيق **تصنيع معدني** متكامل:
التقدير، قوائم المواد، التصنيع، الجودة، الهالك والبواقي، التكلفة الفعلية، وربحية
المشاريع — لأي منتج معدني مصنّع.

المنتجات المدعومة جاهزًا (وقابلة للتوسعة من الواجهة):

الأبواب الحديدية · الأبواب المقاومة للحريق · الشبابيك · الواجهات · البوابات ·
الأسوار والسياج · الدرابزين · السلالم المستقيمة والحلزونية · المظلات ·
الهياكل المعدنية الخفيفة · الأرفف والمنصات · أعمال الصاج · المنتجات حسب الطلب.

يستطيع مدير النظام إضافة **عائلة منتجات جديدة بأبعادها وقواعد مكوناتها وعملياتها
وقالب الجودة الخاص بها دون كتابة أي كود.**

### أبرز المزايا

| المجال | ما تحصل عليه |
|---|---|
| عائلات المنتجات | `dw.product.family` تحدد الأبعاد وطريقة الكمية والوزن والتسعير والعمليات وقالب الجودة وقواعد المكونات |
| محرك الكميات | معادلات موجهة مبنية من حدود مُعرّفة — **بدون `eval` وبدون `safe_eval` وبدون تنفيذ أي كود يكتبه المستخدم** |
| الوزن النظري | معادلات مغلقة للصاج والصاج المضلع والشبك والمواسير الدائرية والمربعة والمستطيلة والزوايا والقطاعات والكمرات والأسياخ، مع إمكانية الإدخال اليدوي |
| قوائم المواد | قائمة خاصة بكل عنصر مع العمليات والتجميعات الفرعية ومواد العميل وخدمات التشغيل الخارجي ومراجعة المخطط، دون المساس بقوائم المواد العامة |
| التكلفة الفعلية | تُبنى من الحركات المخزنية الحقيقية وأزمنة أوامر العمل والهالك والمصروفات المعتمدة وقواعد التحميل — **قابلة لإعادة التشغيل دون تكرار** بضمان قيد فريد |
| الهالك والبواقي | أسباب الهالك، مخطط/غير مخطط، الاعتماد، التقييم، والبواقي القابلة لإعادة الاستخدام بحركات مخزنية قياسية |
| الجودة | قوالب حسب العائلة والمرحلة، اختبارات رقمية ونعم/لا واختيارية ونصية، إجراءات تصحيحية، تكلفة إعادة العمل، ومنع إنهاء أمر التصنيع عند فشل فحص إلزامي |
| المخططات | مراجعات بمرفقات، دورة اعتماد واستبدال، ومنع استخدام مراجعة غير معتمدة في الإنتاج |
| الربحية | على مستوى العنصر وأمر التصنيع وأمر البيع والمشروع والعميل والعائلة والفترة، مع قيمة التحويل الداخلي للعمل داخل نفس الكيان |
| التنبيهات | أحد عشر نوعًا من التنبيهات بحدود قابلة للإعداد حسب الشركة وحسب عائلة المنتج |
| العربية | واجهة مترجمة بالكامل، وتقارير PDF بالعربية واتجاه RTL بخط Amiri مرفق داخل الوحدة |

### المتطلبات

* Odoo 19.0 Community
* تعتمد على: `sale_management` و `mrp` و `project` و `stock_account` و `account`
* **لا تعتمد على أي تطبيق Enterprise ولا تشير إليه.**

### التثبيت

```bash
./odoo-bin -c odoo.conf -d YOURDB -i dw_manufacturing --stop-after-init
```

### الترقية من المرحلة الأولى

```bash
./odoo-bin -c odoo.conf -d YOURDB -u dw_manufacturing --stop-after-init
```

لم يُعَد تسمية أي نموذج ولم يُحذف أي حقل. تم الاحتفاظ بـ `dw.opening` و
`dw.opening.component` و `dw.component.rule` وحقول `dw_*` على `mrp.production`
و `sale.order`، وكذلك معرّفات المجموعات `group_dw_user` و `group_dw_manager`،
لذلك تبقى السجلات والصلاحيات والمرفقات القائمة كما هي.

### الأدلة

انظر مجلد `docs/`، وبالأخص `docs/USER_GUIDE_AR.md` للدليل العربي المختصر.
