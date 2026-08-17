KAWKABAT SEHER ALARQAM — COMPLETE AMIBROKER LOCAL PACKAGE
==========================================================

النسخة المعتمدة:
http://127.0.0.1:8080/kawkabat-v481-amibroker-local.html?v6=1

المجلد المستهدف:
C:\KawkabatSeherAlarqam

أسرع تشغيل لأول مرة:
1) فك ضغط ZIP.
2) شغّل INSTALL_AND_RUN.cmd.
3) افتح AmiBroker.
4) افتح ملف:
   AmiBroker\KAWKABAT_FAST_RT_RUNTIME_PATH_100MS.afl
   وانسخ الكود إلى Formula Editor / Analysis أو طبقه على الشارت.
5) أبقِ AmiBroker مفتوحاً.
6) العجلة ستقرأ:
   C:\KawkabatSeherAlarqam\runtime\ami_live.json

بعد التثبيت:
- START_KAWKABAT_AMIBROKER.cmd
  يشغل الخادم المحلي ويفتح العجلة.

- OPEN_KAWKABAT_WHEEL.cmd
  يفتح العجلة، ويشغل الخدمة تلقائياً إذا كانت متوقفة.

- STOP_KAWKABAT_SERVER.cmd
  يوقف خدمة Kawkabat Python فقط.

- CHECK_KAWKABAT_SYSTEM.cmd
  يفحص الملفات وPython والخدمة والسعر المباشر.

نقاط الخدمة:
Wheel : http://127.0.0.1:8080/kawkabat-v481-amibroker-local.html?v6=1
Quote : http://127.0.0.1:8080/api/quote
Health: http://127.0.0.1:8080/health

مهم:
- لا تشغل py -m http.server على المنفذ 8080 مع هذه الحزمة.
- الخادم المرفق يخدم HTML و /api/quote في نفس الوقت.
- Python المطلوب: 3.12 عبر الأمر py -3.12
- ملف AFL المرفق يحدث ami_live.json كل 100ms تقريباً حسب AmiBroker ومصدر البيانات.
- تم الحفاظ على ملف العجلة الحالي وإضافة استعادة شريطي التحكم الأفقي والعمودي.
