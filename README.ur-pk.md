# پورٹیبل ہرمیس ایجنٹ (Portable Hermes Agent)

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge" alt="English"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/Language-Traditional_Chinese-purple?style=for-the-badge" alt="Traditional Chinese"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/Language-Simplified_Chinese-red?style=for-the-badge" alt="Simplified Chinese"></a>
  <a href="README.es.md"><img src="https://img.shields.io/badge/Language-Spanish-yellow?style=for-the-badge" alt="Spanish"></a>
  <a href="README.ur-pk.md"><img src="https://img.shields.io/badge/Language-Urdu-green?style=for-the-badge" alt="Urdu"></a>
</p>

**Windows کے لیے پورٹیبل AI ایجنٹ** — گرافیکل انٹرفیس، تقریباً 100 ٹولز، LM Studio کے ذریعے مقامی ماڈلز، آواز، موسیقی، ComfyUI، ورک فلو اور اپنے ٹول بنانے کی سہولت۔ سسٹم میں Python یا Node.js نصب کرنے، Docker یا منتظم کے اختیارات کی ضرورت نہیں۔

یہ منصوبہ [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT لائسنس) پر مبنی ہے، لیکن یہ **aivrar کی الگ پورٹیبل تقسیم** ہے۔ اسے اسی ریپوزٹری کے ریلیز صفحے سے حاصل کریں؛ اصل Hermes Agent کی تنصیب کی ہدایات اس پورٹیبل پیکیج کے لیے نہیں ہیں۔

---

## خصوصیات

- گہرے رنگ کا Tkinter ڈیسک ٹاپ انٹرفیس: چیٹ، سائیڈبار، سیشن، تصویر منسلک کرنا، رہنمائی کا موڈ، API کلید کا سیٹ اَپ اور اجازتوں کا پینل۔
- انٹرفیس کی زبانیں: انگریزی، روایتی چینی، آسان چینی اور ہسپانوی؛ چلتی ہوئی ایپ میں زبان تبدیل کی جا سکتی ہے۔ اس README کا اردو ترجمہ انٹرفیس میں اردو زبان کا وعدہ نہیں ہے۔
- بیس سے زیادہ ٹول گروپس میں تقریباً 100 ٹولز: LM Studio، متن سے آواز، موسیقی، ComfyUI، ورک فلو، ٹول میکر، تلاش، GPU کی حالت اور اندرونی رہنما۔
- [TTS Server](https://github.com/aivrar/portable-tts-server)، [Music Server](https://github.com/aivrar/portable-music-server) اور [ComfyUI](https://github.com/aivrar/comfyui-portable-installer) کی پورٹیبل توسیعات ضرورت پڑنے پر انسٹال ہوتی ہیں۔
- اصل Hermes Agent کی فائل، براؤزر، میموری، اسکلز اور پیغام رسانی کی سہولتیں بھی شامل ہیں۔

LM Studio پینل سرور کا پتہ اور اختیاری API کلید فعال `HERMES_HOME` کی `.lmstudio_config` فائل میں محفوظ کرتا ہے، ایپ کے سورس کوڈ میں نہیں۔ دونوں اپ ڈیٹ راستے یہ ذاتی ڈیٹا محفوظ رکھتے ہیں، اور ریلیز ZIP میں یہ فائل شامل نہیں ہوتی۔ کلید کو خفیہ رکھیں؛ محفوظ کردہ کلید ہٹانے کے لیے کلید کا خانہ خالی کر کے **Save** دبائیں۔

---

## آغاز

1. [Portable Hermes Agent کے ریلیز صفحے](https://github.com/aivrar/portable-hermes-agent/releases/latest) سے تازہ `portable-hermes-agent-v*.zip` ڈاؤن لوڈ کریں۔ اسے عام فولڈر، مثلاً `C:\Users\YourName\Portable-Hermes-Agent`، میں کھولیں؛ `C:\Program Files` جیسے محفوظ سسٹم فولڈر سے بچیں۔ فولڈر کے راستے میں خالی جگہ ہو سکتی ہے، لیکن `!`، `%` یا `^` نہیں؛ ورنہ لانچرز نہیں چلیں گے۔
2. **`START.bat`** پر ڈبل کلک کریں۔ پہلی بار یہ پورٹیبل فولڈر کے اندر ہی Python 3.14، **`NousResearch/hermes-agent` سے Hermes Agent کا تازہ ترین بنیادی حصہ (core)**، اس کے مقررہ پیکیج اور LM Studio SDK ڈاؤن لوڈ کرتا ہے، اور ایک الگ عمل میں جانچتا ہے کہ نیا core پورٹیبل ٹولز اور GUI کے ساتھ کام کرتا ہے۔
3. کلاؤڈ ماڈل کے لیے GUI میں API کلید سیٹ کریں، یا [LM Studio](https://lmstudio.ai) کا مقامی سرور چلا کر GUI کے LM Studio پینل میں ماڈل منتخب کریں۔

| فائل | کام |
|---|---|
| `START.bat` | گرافیکل انٹرفیس شروع کرنے کا آسان ترین راستہ |
| `UPDATE.bat` | پورٹیبل حصہ اپ ڈیٹ کرنا، اور منظوری پر core بھی |
| `hermes_gui.bat` | گرافیکل انٹرفیس کھولنا |
| `hermes.bat` | کمانڈ لائن کھولنا |
| `install.bat` | پہلی بار دستی سیٹ اَپ |

بغیر سوالات کے سیٹ اَپ کے لیے `install.bat --yes` چلائیں۔

## دو الگ اپ ڈیٹ راستے

Portable Hermes کے **دو حصے ہیں جو الگ الگ اپ ڈیٹ ہوتے ہیں**:

| حصہ | ماخذ | مواد |
|---|---|---|
| **پورٹیبل حصہ** | [`aivrar/portable-hermes-agent` ریلیزز](https://github.com/aivrar/portable-hermes-agent/releases/latest) | Windows لانچرز، GUI، پورٹیبل ٹولز اور اسکلز، انسٹالر اور اپ ڈیٹر |
| **Hermes core** | `NousResearch/hermes-agent` (تازہ ترین `main`) | خود Agent |

Hermes بند کریں اور **`UPDATE.bat`** چلائیں۔ یہ پہلے پورٹیبل حصہ اپ ڈیٹ کرتا ہے (ہر فائل کی جانچ، صرف پورٹیبل فائلیں تبدیل، کسی ناکامی پر سب کچھ واپس)، پھر بتاتا ہے کہ core کتنی تبدیلیاں پیچھے ہے اور پوچھتا ہے کہ کیا اسے اپ ڈیٹ کیا جائے۔ بغیر سوالات کے: `UPDATE.bat --yes` (صرف پورٹیبل حصہ) یا `UPDATE.bat --yes --core` (دونوں)۔ آپ چیٹ میں Hermes سے بھی core کی اپ ڈیٹ چیک یا انسٹال کرنے کو کہہ سکتے ہیں۔

اگر آپ v1.4.18 یا پرانے ورژن سے آ رہے ہیں تو پہلی بار `UPDATE.bat` نئے لانچرز انسٹال کرتا ہے اور اسے دوبارہ چلانے کو کہتا ہے؛ دوسری بار اپ ڈیٹ مکمل ہو جاتی ہے۔

**جب نئے core کو نیا Python چاہیے** (v1.4.18 اور پرانی انسٹالیشنز میں Python 3.13 ہے، موجودہ core کو 3.14 چاہیے)، تو core والا مرحلہ وضاحت کرتا ہے اور پوچھتا ہے `Upgrade the portable Python to 3.14.9 now? [y/N]`۔ `y` پر `python_embedded` کا نام بدل کر `python_embedded.old-<ورژن>` کر دیا جاتا ہے (محفوظ رہتا ہے، حذف نہیں ہوتا)، نیا Python (تقریباً 18 MB) اور پیکیج (عموماً 150-300 MB) ڈاؤن لوڈ ہوتے ہیں اور core انسٹال ہوتا ہے؛ ناکامی پر سب کچھ واپس ہو جاتا ہے۔ `N` پر کچھ نہیں بدلتا۔ `UPDATE.bat --yes --core` بغیر پوچھے اپ گریڈ کرتا ہے۔ Hermes ٹھیک چلنے پر پرانا فولڈر خود حذف کر دیں۔

نیا core فائلیں بدلنے سے پہلے ایک عارضی فولڈر میں تیار اور الگ عمل میں جانچا جاتا ہے؛ ناکامی پر فائلیں پہلے جیسی ہو جاتی ہیں اور بدلے ہوئے پیکیج واپس لا کر جانچے جاتے ہیں (اگر سب واپس نہ ہو سکیں تو اپ ڈیٹ یہ بتاتا ہے، اور `UPDATE.bat` دوبارہ چلانے سے کام مکمل ہو جاتا ہے)۔ `.env`، `cli-config.yaml`، `HERMES_HOME` (کسٹم ٹولز، LM Studio ترتیبات، زبان)، `extensions\` اور `workflows\` کبھی نہیں چھیڑے جاتے؛ `python_embedded\` صرف core کے لیے پیکیج انسٹال کرتے وقت اور اوپر بیان کردہ Python اپ گریڈ میں بدلتا ہے۔ core اپ ڈیٹ کے بعد Hermes دوبارہ شروع کریں۔ Git نقول (ڈویلپرز) `git pull` سے اپ ڈیٹ کریں۔

---

## ضروریات اور دستاویزات

- Windows 10 یا 11۔
- کلاؤڈ AI کے لیے انٹرنیٹ؛ مقامی ماڈل کے لیے مناسب NVIDIA GPU، ترجیحاً کم از کم 8 GB VRAM۔
- سسٹم Python، سسٹم Node.js، Docker یا منتظم کے اختیارات ضروری نہیں۔

ایپ میں قابلِ تلاش رہنما (`search_guide`) موجود ہے۔ ہر [ریلیز](https://github.com/aivrar/portable-hermes-agent/releases/latest) کے ساتھ PDF کتابچہ بھی ملتا ہے۔ غیر ترجمہ شدہ تازہ تفصیلات کے لیے [انگریزی پورٹیبل README](README.md) دیکھیں۔

## شکریہ اور لائسنس

اصل فریم ورک: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT لائسنس)۔ پورٹیبل توسیعات: [aivrar](https://github.com/aivrar)۔ مزید تفصیل [LICENSE](LICENSE) میں ہے۔
