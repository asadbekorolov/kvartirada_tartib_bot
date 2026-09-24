# 🏠 Telegram Kvartira Boshqaruv Boti (`kvartira_bot`)

## 1, 2 va 3-Bosqich: To'liq Arxitektura, Bozorlik (Split-Bill), Mehmon, Fond va Production/Deploy

Kvartiradagi kunlik navbatchilik, kir yuvish, dam olish kunlari bozorlik xarajatlarini teng taqsimlash (Split-Bill), 11 bandlik tozalash, 19L ichimlik suvi ta'minoti, mehmon ogohlantirishlari, jarima fondi va kvartira qoidalarini avtomatlashtiruvchi to'liq Telegram bot.

---

## 📌 Yangi Imkoniyatlar (3-Bosqich)

1. **Bozorlik va Hisob-kitob Tizimi (Split-Bill) — `/bozorlik`:**
   - Bozorlik qilgan juftlik xarid summasi va izohini kiritadi: `/bozorlik 360000 Go'sht, yog' va sabzavotlar`.
   - Shuningdek xarid cheki rasmini yuborib, captionda shu buyruqni berish mumkin.
   - Bot barcha faol a'zolar soniga ($N$) qarab ulushni hisoblaydi: $\text{Ulush} = \frac{\text{Summa}}{N}$.
   - Xarid egasi avtomatik `✅ To'landi` deb belgilanadi.
   - Har bir xonadosh o'z ulushini bergach, `[💸 To'ladim]` tugmasini bosadi va hisobot real vaqtda yangilanadi.

2. **Mehmon Ogohlantirish Tizimi — `/mehmon`:**
   - Qoida: Mehmon kelishidan kamida 3–4 soat oldin umumiy guruhda ogohlantirish shart.
   - Format: `/mehmon [kelish vaqti] [odam soni] [izoh]` (Masalan: `/mehmon 19:00 2 ta kursdoshim`).
   - Bot guruhdagi barcha xonadoshlarni ogohlantirib, umumiy joylar (koridor, zal, oshxona, vanna) ozodaligiga e'tibor qaratishni eslatadi.

3. **Kvartira Fondi va Jarimalar Balansi — `/fond` yoki `/jarimalar`:**
   - Yig'ilgan (to'langan) va to'lanishi kutilayotgan jarimalar balansi.
   - Kimda qancha qarzdorlik borligi va sabablari.
   - Mas'ul xonadosh uchun inline `[✅ To'landi deb belgilash]` tugmasi.

4. **Kvartiraning 6 Ta Asosiy Qoidasi — `/qoidalar`:**
   1. Shaxsiy idishlar (ovqatlangan zahoti yuviladi).
   2. Umumiy joylar tartibi (shaxsiy kiyim, noutbuk, zaryadlagich sochib qo'yilmaydi).
   3. Bozorlik shaffofligi (chek va hisob-kitob tashlanadi).
   4. Mehmon ogohlantirishi (kamida 3–4 soat oldin).
   5. Kechki sukunat (22:30 dan boshlab quloqchin, qo'ng'iroqlar balkonda).
   6. Jarima fondi (sababsiz qoidabuzarlik uchun 15,000 so'm).

5. **Production & Docker Deploy:**
   - `Dockerfile` va `docker-compose.yml` (SQLite ma'lumotlari Docker volume da saqlanadi).
   - Avtomatik restart (`unless-stopped`), log rotatsiyasi.
   - Barcha 14 ta bot buyruqlari Telegram menyusiga (`BotCommand`) avtomatik o'rnatiladi.

---

## 📂 Fayllar Strukturasi

```text
kvartira_bot/
├── .env.example            # Konfiguratsiya shabloni
├── .env                    # Faol konfiguratsiya fayli
├── Dockerfile              # Docker konteyner fayli (Python 3.11-slim)
├── docker-compose.yml      # Docker Compose deploy konfiguratsiyasi
├── .dockerignore           # Docker build optimizatsiyasi
├── bot.py                  # Botni ishga tushirish (Entrypoint va barcha routerlar)
├── config.py               # Pydantic Settings
├── requirements.txt        # Loyiha kutubxonalari
├── database/
│   ├── base.py             # DeclarativeBase
│   ├── models.py           # User, DutyHistory, CleaningChecklistState, PenaltyFund, RotationState, Expense, ExpenseShare
│   └── session.py          # Async engine, sessionmaker va init_db
├── services/
│   ├── duty_service.py     # Uzluksiz Round-Robin, rebalance, kir va suv hisobi
│   ├── cleaning_service.py # 11 bandlik tozalash checklisti va progress bar
│   ├── expense_service.py  # Bozorlik split-bill logikasi va to'lov nazorati
│   └── scheduler.py        # 08:00, 20:00, 22:30 va Shanba 09:00 cron xabarnomalari
├── handlers/
│   ├── start.py            # /start (FSM 1-Xona/2-Xona), /leave, /azolar, /profil
│   ├── duty.py             # /bugun (5 vazifa), /ertaga, /haftalik, /suv (2 haftalik)
│   ├── cleaning.py         # /tozalash (11 bandlik interaktiv checklist)
│   ├── swap.py             # /almashtirish ([Roziman] / [Rad etaman])
│   ├── expense.py          # /bozorlik (Split-Bill va chek fotosi)
│   ├── guest.py            # /mehmon (Kelish vaqti, soni va izoh)
│   ├── fund.py             # /fond va /jarimalar balansi
│   └── rules.py            # /qoidalar (6 ta asosiy qoida)
├── keyboards/
│   ├── inline.py           # Barcha inline tugmalar (split-bill, checklist, swap, fond)
│   └── reply.py            # Asosiy doimiy navigatsiya menyusi
└── tests/
    └── test_system.py      # Tizimni tekshiruvchi 10 ta to'liq avtotest
```

---

## 🚀 Ishga Tushirish va Deploy

### 1. Mahalliy muhitda (Local Python):
```bash
# Virtual muhitni faollashtirish
.venv\Scripts\activate

# Testlarni yurgizish
python tests/test_system.py

# Botni ishga tushirish
python bot.py
```

### 2. Docker & Docker Compose orqali (Production):
```bash
# Konteynerni fonda ishga tushirish:
docker-compose up -d --build

# Loglarni kuzatish:
docker-compose logs -f

# To'xtatish:
docker-compose down
```
