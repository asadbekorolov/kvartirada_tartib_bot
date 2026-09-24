from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import settings

router = Router(name="rules_router")

RULES_TEXT = (
    f"📜 <b>{settings.APARTMENT_NAME} — Asosiy 6 Ta Tartib Qoidasi</b>\n\n"
    "1️⃣ 🍽 <b>Shaxsiy Idishlar Tartibi:</b>\n"
    "Ovqatlangan zahoti har bir xonadosh o'z idish-tovog'ini, choynak va kosasini "
    "darhol yuvib, quritish joyiga qo'yishi shart. Idishlarni rakovinada qoldirish qat'iyan taqiqlanadi.\n\n"
    "2️⃣ 🧹 <b>Umumiy Joylar Ozodaligi:</b>\n"
    "Koridor, zal, xontaxta va oshxona stollariga shaxsiy kiyim-kechak, paypoq, "
    "noutbuk, quvvatlagich (zaryadka) yoki sumkalarni sochib qo'yish mumkin emas. Har bir buyum o'z xonasida turishi kerak.\n\n"
    "3️⃣ 🧾 <b>Bozorlik Shaffofligi (Split-Bill):</b>\n"
    "Bozorlik qilgan navbatchi juftlik xarid qilingan mahsulotlar chekini va jami hisob-kitobni "
    "darhol guruhga <code>/bozorlik [summa] [izoh]</code> orqali taqdim etishi shart.\n\n"
    "4️⃣ 👥 <b>Mehmon Ogohlantirishi:</b>\n"
    "Kvartiraga mehmon taklif qilmoqchi bo'lgan xonadosh kamida <b>3–4 soat oldin</b> "
    "guruhda <code>/mehmon [vaqt] [soni] [izoh]</code> buyrug'i orqali barchani ogohlantirishi shart.\n\n"
    "5️⃣ 🤫 <b>Kechki Sukunat Rejimi (22:30):</b>\n"
    "Soat <b>22:30</b> dan boshlab xonalarda baland ovozda gaplashish va shovqin qilish taqiqlanadi. "
    "Telefon qo'ng'iroqlari balkonda amalga oshiriladi, video/musiqalar esa faqat quloqchinda (naushnik) eshitiladi.\n\n"
    "6️⃣ 💰 <b>Jarima Fondi Tizimi:</b>\n"
    "Navbatchilikni bajarmaslik, idishlarni tashlab ketish yoki kechki sukunatni sababsiz buzish holatlari uchun "
    f"jarima jamg'armasiga <b>{settings.DAILY_FINE_AMOUNT:,} so'm</b> jarima yoziladi. Mablag' faqat umumiy ro'zg'or ehtiyojlariga sarflanadi.\n\n"
    "<i>Birgalikdagi tartib va ahillik barchamiz uchun qulaylik yaratadi! 🤝✨</i>"
)


@router.message(Command("qoidalar"))
async def handle_rules_command(message: Message):
    """Display the 6 fundamental house rules of the apartment."""
    await message.answer(RULES_TEXT)
