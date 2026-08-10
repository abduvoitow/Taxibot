import re
import json
import logging
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from config import GEMINI_API_KEYS

ai_clients = []
for idx, key in enumerate(GEMINI_API_KEYS):
    try:
        c = genai.Client(api_key=key)
        ai_clients.append(c)
    except Exception as e:
        logging.warning(f"GenAI Client #{idx+1} yaratib bo'lmadi: {e}")

_current_client_index = 0

def get_current_client():
    global _current_client_index
    if not ai_clients:
        return None
    return ai_clients[_current_client_index]

def rotate_client():
    global _current_client_index
    if not ai_clients:
        return None
    _current_client_index = (_current_client_index + 1) % len(ai_clients)
    logging.info(f"Gemini API key almashtirildi. Yangi key indeksi: {_current_client_index + 1}")
    return ai_clients[_current_client_index]

# Kirillchani Lotinchaga o'girish uchun lug'at
CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'j', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
    'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'x', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sh',
    'ъ': '\'', 'ы': 'i', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya', 'ў': 'o\'', 'қ': 'q', 'ғ': 'g\'', 'ҳ': 'h'
}

def normalize_text(text: str) -> str:
    text = text.lower()
    # Hamma turdagi xato va har xil tutuq belgilarni bitta standart ' ga o'giramiz
    text = re.sub(r'[`\u2018\u2019\u201c\u201d]', "'", text)
    
    for cyr, lat in CYRILLIC_TO_LATIN.items():
        text = text.replace(cyr, lat)
    return text

def extract_time(text: str) -> str:
    """
    Xabardan vaqt va sanani aqlli tarzda ajratib oladi.
    Erta, indin, 3-sana, soat 3 da, shanba kabi ko'rinishlarni qo'llab-quvvatlaydi.
    """
    t = normalize_text(text)
    now = datetime.now()

    MONTHS_UZ = [
        "yanvar", "fevral", "mart", "aprel", "may", "iyun",
        "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"
    ]
    WEEKDAYS_UZ = {
        "dushanba": 0, "seshanba": 1, "chorshanba": 2,
        "payshanba": 3, "juma": 4, "shanba": 5, "yakshanba": 6
    }

    # --- Sana aniqlash ---
    date_label = ""

    if re.search(r'\bhozir\b', t):
        date_label = "Hozir"
    elif re.search(r'\bbugun\b', t):
        date_label = f"Bugun ({now.strftime('%d-%B').replace(now.strftime('%B'), MONTHS_UZ[now.month-1])})"
    elif re.search(r'\berta(ga)?\b', t):
        erta = now + timedelta(days=1)
        date_label = f"Erta ({erta.strftime('%d')}-{MONTHS_UZ[erta.month-1]})"
    elif re.search(r'\bindin(ga)?\b', t):
        indin = now + timedelta(days=2)
        date_label = f"Indin ({indin.strftime('%d')}-{MONTHS_UZ[indin.month-1]})"
    else:
        # Hafta kuni (masalan: shanba, juma kuni)
        for day_name, day_num in WEEKDAYS_UZ.items():
            if re.search(r'\b' + day_name + r'\b', t):
                days_ahead = (day_num - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target = now + timedelta(days=days_ahead)
                date_label = f"{day_name.capitalize()} ({target.strftime('%d')}-{MONTHS_UZ[target.month-1]})"
                break

        # Sana raqam bilan (masalan: 3-sana, 3-ga, 3 da, 14-avgust)
        if not date_label:
            # Oyni ham aniqlash (masalan: "14 avgustga")
            month_match = re.search(r'(\d{1,2})\s*[-–]?\s*(' + '|'.join(MONTHS_UZ) + r')', t)
            if month_match:
                day = int(month_match.group(1))
                month_name = month_match.group(2)
                month_num = MONTHS_UZ.index(month_name) + 1
                year = now.year if month_num >= now.month else now.year + 1
                try:
                    target_date = datetime(year, month_num, day)
                    date_label = f"{day}-{month_name}"
                except ValueError:
                    date_label = f"{day}-{month_name}"
                # Faqat raqam (masalan: 3-sana, 3 chi, 3 inchi)
                sana_match = re.search(r'(\d{1,2})\s*[-–]?\s*(sana|chi|iga|inchi)\b', t)
                if sana_match:
                    day = int(sana_match.group(1))
                    month_num = now.month if day >= now.day else (now.month % 12) + 1
                    date_label = f"{day}-{MONTHS_UZ[month_num-1]}"

    # --- Soat aniqlash ---
    time_label = ""

    # Ertalab/kechqurun konteksti
    is_morning = bool(re.search(r'\b(ertalab|tong|saharda|subhida)\b', t))
    is_evening = bool(re.search(r'\b(kechqurun|kechga|kechasi|oqshom)\b', t))

    soat_match = re.search(r'soat\s*(\d{1,2})(?:[:\.](\d{2}))?\s*(larda|da|ga|cha)?', t)
    if soat_match:
        hour = int(soat_match.group(1))
        minute = soat_match.group(2) or "00"
        # 1-12 oraliqda bo'lsa, ertalab/kechqurun kontekstiga qarab sozlaymiz
        if 1 <= hour <= 12:
            if is_evening and hour < 12:
                hour += 12
            elif not is_morning and not is_evening and hour <= 6:
                hour += 12  # Default: qorong'i soatlarni PM deb olish
        time_label = f"Soat {hour:02d}:{minute}"
    elif re.search(r'\b(\d{1,2})\s*(larda|da)\b', t):
        m = re.search(r'\b(\d{1,2})\s*(larda|da)\b', t)
        hour = int(m.group(1))
        if is_evening and hour < 12:
            hour += 12
        time_label = f"Soat {hour:02d}:00"
    elif is_morning:
        time_label = "Ertalab"
    elif is_evening:
        time_label = "Kechqurun"
    elif re.search(r'\b(tush|obedda|tushda|peshin)\b', t):
        time_label = "Tushda (~12:00)"
    elif re.search(r'\b(abotda|saharlab)\b', t):
        time_label = "Saharlab"

    # --- Natijani birlashtirish ---
    parts = [p for p in [date_label, time_label] if p]
    if parts:
        return ", ".join(parts)
    return "Xabarda"

# O'zbekistonning barcha viloyatlari, shahar va tumanlari ro'yxati
# Kichik tuman nomi yozilsa ham avtomatik bosh viloyatiga biriktiriladi
CITIES = {
    "toshkent": [
        "toshkent", "toshknet", "tosh", "tashkent", "tash", "teshkent", "bekobod", "bo'ka", "bo'stonliq", "chinoz", 
        "qibray", "ohangaron", "oqqo'rg'on", "parkent", "piskent", "quyi chirchiq", 
        "o'rta chirchiq", "yangiyo'l", "yuqori chirchiq", "zangiota", "chirchiq", 
        "olmaliq", "angren", "yunusobod", "chilonzor", "mirobod", "mirzo ulug'bek", 
        "sergeli", "yashnobod", "olmazor", "uchtepa", "shayxontohur", "yakkasaroy", "bektemir"
    ],
    "samarqand": [
        "samarqand", "samarkand", "sam", "samarkant", "samarqan", "bulung'ur", "ishtixon", "jomboy", "kattaqo'rg'on", 
        "narpay", "nurobod", "oqdaryo", "paxtachi", "payariq", "pastdarg'om", "qo'shrabot", 
        "tayloq", "urgut"
    ],
    "sirdaryo": [
        "sirdaryo", "sirdarya", "sirdary", "guliston", "shirin", "boyovut", "mirzaobod", 
        "oqoltin", "sayxunobod", "sardoba", "xavos", "yangiyer"
    ],
    "jizzax": [
        "jizzax", "jizzakh", "jizax", "jizak", "jizzah", "arnasoy", "baxmal", "do'stlik", "forish", "g'allaorol", 
        "sharof rashidov", "mirzacho'l", "paxtakor", "yangiobod", "zafarobod", "zarbdor", "zomin"
    ],
    "farg'ona": [
        "farg'ona", "fargona", "fergana", "farg`ona", "fargon", "fergan", "oltiariq", "bog'dod", "beshariq", 
        "buvayda", "dang'ara", "furqat", "qo'shtepa", "quva", "rishton", "so'x", "toshloq", 
        "uchko'prik", "yozyovon", "qo'qon", "quqon", "marg'ilon", "quvasoy"
    ],
    "andijon": [
        "andijon", "andijan", "andjon", "anjon", "asaka", "baliqchi", "bo'z", "buloqboshi", "izboskan", 
        "jalaquduq", "marhamat", "oltinko'l", "paxtaobod", "qo'rg'ontepa", "shahrixon", 
        "ulug'nor", "xo'jaobod", "xonobod"
    ],
    "namangan": [
        "namangan", "namagan", "namangon", "nam", "chortoq", "chust", "kosonsoy", "mingbuloq", "norin", "pop", 
        "to'raqo'rg'on", "uchqo'rg'on", "uychi", "yangiqo'rg'on", "davlatobod"
    ],
    "buxoro": [
        "buxoro", "bukhara", "buxara", "bixoro", "buxor", "olot", "qorako'l", "qorovulbozor", "romitan", "shofirkon", 
        "vobkent", "g'ijduvon", "jondor", "kogon", "peshku"
    ],
    "navoiy": [
        "navoiy", "navoi", "navaiy", "navo", "qiziltepa", "nurota", "tomdi", "uchquduq", "xatirchi", 
        "karmana", "zarafshon", "konimex"
    ],
    "qashqadaryo": [
        "qashqadaryo", "qarshi", "qashqa", "kashkadarya", "chiroqchi", "dehqonobod", "g'uzor", "qamashi", 
        "kasbi", "kitob", "koson", "mirishkor", "muborak", "nishon", "shahrisabz", "yakkabog'", "ko'kdala"
    ],
    "surxondaryo": [
        "surxondaryo", "termez", "surxon", "termiz", "surxandarya", "angor", "boysun", "denov", "jarqo'rg'on", 
        "qiziriq", "qumqo'rg'on", "muzrabot", "oltinsoy", "sariosiyo", "sheroobod", "sho'rchi", "uzun", "bandixon"
    ],
    "xorazm": [
        "xorazm", "xiva", "urganch", "xorazim", "xarezm", "xoraz", "bog'ot", "gurlan", "qo'shko'pir", "shovat", 
        "xonqa", "hazarasp", "yangiariq", "yangibozor", "tuproqqal'a"
    ],
    "qoraqalpog'iston": [
        "qoraqalpog'iston", "qoraqalpoq", "nukus", "karakalpak", "qoraqalpogiston", "amudaryo", "beruniy", "chimboy", "ellikqal'a", 
        "kegeyli", "mo'ynoq", "qanliko'l", "qo'ng'irot", "qorao'zak", "shumanay", "taxtako'pir", 
        "to'rtko'l", "xo'jayli", "taxiatosh", "bo'zatov"
    ]
}

EXCLUDED_ORIGINS = {
    "bir", "birdan", "ikki", "uch", "to'rt", "tort", "besh", "olti", "yetti", "sakkiz", "to'qqiz", "toqqiz", "o'n", "on",
    "bosh", "avval", "qayta", "bitta", "har", "shu", "o'sha", "osha", "uy", "yana", "soat", "kun", "hafta", "oy", "yili", "yil"
}

EXCLUDED_DESTINATIONS = {
    "men", "manga", "menga", "sen", "sanga", "senga", "un", "unga", "biz", "bizga", "siz", "sizga", "ular", "ularga",
    "bir", "birga", "bosh", "boshqa", "hamma", "hammaga", "barcha", "barchaga", "dostlar", "do'stlar", "gruppa", "guruh",
    "kanal", "bot", "taksi", "taxi", "mashina", "moshina", "vaqt", "soat", "ish", "uy", "ishga", "uyga", "tush", "kech"
}

def is_plausible_place_name(word: str) -> bool:
    """
    So'z haqiqiy joy nomiga o'xshaydi yoki yo'qligini tekshiradi.
    Quyidagi holatlarni rad etadi:
      - Unli harfi yo'q so'zlar (masalan: 'rwerwer', 'fdsafdsa')
      - 4 ta yoki undan ko'p ketma-ket undosh harf bor so'zlar
      - Juda qisqa (2 ta va undan kam) so'zlar
    """
    if len(word) < 3:
        return False
    
    vowels = set("aeiou")
    if not any(c in vowels for c in word):
        return False
    
    # 4 ta ketma-ket undosh harfni tekshirish
    consonants_streak = 0
    for ch in word:
        if ch not in vowels and ch.isalpha():
            consonants_streak += 1
            if consonants_streak >= 4:
                return False
        else:
            consonants_streak = 0
    
    return True

def extract_local_locations(text_lower: str):
    """
    Matndan -dan / -ga qo'shimchalari bo'lgan har qanday mahalliy joy, tumancha,
    mahalla yoki shahar nomlarini ajratib oladi.
    """
    t = normalize_text(text_lower)
    
    from_loc = None
    to_loc = None
    
    for match in re.finditer(r'\b([a-z\‘\'`ʻ]{2,})\s*(?:dan|den)\b', t):
        cand = match.group(1).strip()
        if cand not in EXCLUDED_ORIGINS and is_plausible_place_name(cand):
            from_loc = cand.capitalize()
            break
            
    for match in re.finditer(r'\b([a-z\‘\'`ʻ]{2,})\s*(?:ga|ge|qa|ka)\b', t):
        cand = match.group(1).strip()
        if cand not in EXCLUDED_DESTINATIONS and is_plausible_place_name(cand):
            to_loc = cand.capitalize()
            break
            
    return from_loc, to_loc

def extract_cities_info(text: str) -> list:
    text_lower = text.lower()
    found_cities = []
    
    for main_city, variants in CITIES.items():
        for variant in variants:
            safe_variant = variant.replace("'", r"[']?")
            pattern = r'\b' + safe_variant + r'([\w\-]*)\b'
            match = re.search(pattern, text_lower)
            if match:
                found_cities.append({
                    "city": main_city,
                    "name": variant.capitalize(),
                    "suffix": match.group(1)
                })
                break
                
    return found_cities

def extract_price(text_lower: str) -> str:
    """
    Xabardan narxni mukammal ajratib oladi.
    100, 100k, 100 ming, 100.000, 50, 150, 100ga, 50dan, 20000, 100$ kabilar.
    """
    # 0. Dollar ($ yoki dollar, usd) narxlari
    dollar_match = re.search(r'(\$\s*\d+|\d+\s*\$|\d+\s*(?:dollar|usd)\b)', text_lower)
    if dollar_match:
        num = re.search(r'\d+', dollar_match.group(1)).group(0)
        return f"{num} $"

    # 1. 000 bilan tugaydigan yoki ming, k, m, so'm bilan kelgan aniq narxlar
    m = re.search(r'(\d{1,4}[\s\.\,]*000|\d+\s*(?:ming|min|k|m|so[\']?m|som|sum)\b)', text_lower)
    if m:
        val = m.group(1).strip()
        if re.search(r'\d+[\s\.\,]*000$', val):
            clean_num = re.sub(r'[^\d]', '', val)
            return f"{int(clean_num):,}".replace(',', '.') + " so'm"
        elif re.search(r'(ming|min|k|m)$', val):
            num = re.search(r'\d+', val).group(0)
            return f"{num}.000 so'm"
        return val

    # 2. Qo'shimchali narxlar (masalan: 100ga, 50dan, 150ga, 10ga)
    m = re.search(r'\b(\d{2,4})\s*(?:ga|ge|qa|ka|dan|den)\b', text_lower)
    if m:
        num = int(m.group(1))
        if 10 <= num <= 999:
            return f"{num}.000 so'm"

    # 3. Yolg'iz raqamlar (masalan: "samarqanddan toshkentga 100", "50 2ta odam")
    words = text_lower.split()
    for w in words:
        clean_w = re.sub(r'[^\d]', '', w)
        if clean_w.isdigit():
            num = int(clean_w)
            if re.search(r'soat|sana|kun|odam|kishi|joy|ta|998', w):
                continue
            if 10 <= num <= 999:
                return f"{num}.000 so'm"
            elif 1000 <= num <= 999999:
                return f"{num:,}".replace(',', '.') + " so'm"

    return "Kelishiladi"

def is_taxi_order(text: str) -> dict:
    """
    Regex yordamida matnni tahlil qilib shaharlarni, mahalliy joy nomlarini va yo'nalishni ajratib oladi.
    """
    if not text or len(text) < 4:
        return {"is_taxi": False}

    text_lower = normalize_text(text)
    
    # 1. Spam, reklama, ssilkalar va bot komandalarini filtrlash
    if re.search(r'(https?://|t\.me/|www\.|@\w+(?i:bot))', text_lower):
        return {"is_taxi": False}

    # 2. Mahalliy nomlar (-dan / -ga qo'shimchalar orqali)
    local_from, local_to = extract_local_locations(text_lower)
    
    # 3. Shaharlar bazasi orqali aniqlash
    cities_info = extract_cities_info(text_lower)
    
    from_loc = local_from
    to_loc = local_to
    
    # Agar bazadagi shaharlar topilgan bo'lsa, ularni ham inobatga olamiz
    if cities_info:
        for c in cities_info:
            if ("dan" in c["suffix"] or "den" in c["suffix"]) and not from_loc:
                from_loc = c["name"]
            elif ("ga" in c["suffix"] or "ge" in c["suffix"] or "qa" in c["suffix"] or "ka" in c["suffix"]) and not to_loc:
                to_loc = c["name"]
                
        if not from_loc and not to_loc:
            if len(cities_info) >= 2:
                from_loc = cities_info[0]["name"]
                to_loc = cities_info[1]["name"]
            elif len(cities_info) == 1:
                if "dan" in cities_info[0]["suffix"] or "den" in cities_info[0]["suffix"]:
                    from_loc = cities_info[0]["name"]
                else:
                    to_loc = cities_info[0]["name"]

    # 4. Taksi kalit so'zlari
    taxi_keywords = [
        r"bor", r"kerak", r"odam", r"joy", r"taksi", r"taxi", r"mashina", r"moshina",
        r"ketamiz", r"ketadigan", r"qaytamiz", r"chiqadi", r"boriladi", r"obketaman", r"ketyapman",
        r"ming", r"som", r"so'm", r"min", r"soat", r"bugun", r"ertalab",
        r"pochta", r"posilka", r"pasilka", r"yuk", r"narsa", r"hujjat", r"dokument", 
        r"konvert", r"sumka", r"karobka", r"quti", r"dori", r"dastavka", r"yukcha", r"bervorish"
    ]
    
    has_keyword = any(re.search(r'\b' + kw.replace("'", r"[']?") + r'[\w\-]*\b', text_lower) for kw in taxi_keywords)
    has_db_city = bool(cities_info)
    is_local_only = (from_loc or to_loc) and not has_db_city

    # Karar qabul qilish:
    # - Bazaviy shahar topilgan + ikki manzil: to'g'ridan tasdiqlash
    # - Mahalliy nomlar (bazasiz): faqat taksi kalit so'zi ham bo'lsa qabul qilish
    # - Faqat gibberish bo'lsa: rad etamiz
    should_accept = False
    if has_db_city and (from_loc and to_loc):
        should_accept = True
    elif has_db_city and (from_loc or to_loc) and has_keyword:
        should_accept = True
    elif is_local_only and (from_loc and to_loc) and has_keyword:
        should_accept = True
    elif is_local_only and (from_loc or to_loc) and has_keyword:
        should_accept = True

    if should_accept:
        final_from = from_loc or "Noma'lum"
        final_to = to_loc or "Noma'lum"
        route_key = f"{final_from.lower()}-{final_to.lower()}"
        
        price = extract_price(text_lower)
        
        phone_matches = re.findall(r'(?:\+?998[\s\-\(]*\d{2}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}|\b\d{2}[\s\-\(]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b)', text)
        phone = ", ".join([p.strip() for p in phone_matches]) if phone_matches else "Xabarning o'zida"
        
        package_words = r'(pochta|posilka|pasilka|yuk|narsa|hujjat|dokument|konvert|sumka|karobka|quti|dori|dastavka|yukcha)'
        is_package = bool(re.search(package_words, text_lower))
        
        pass_match = re.search(r'(\d+|bir|ikki|uch|to[\']?rt|toq|besh)\s*(ta\s*odam|kishi|ta\s*joy|odam|joy|ta)', text_lower)
        passengers = pass_match.group(1).title() + " ta" if pass_match else "Ko'rsatilmagan"
        
        extracted_time = extract_time(text)
        
        return {
            "is_taxi": True,
            "route": route_key,
            "from_location": final_from,
            "to_location": final_to,
            "price": price,
            "phone_number": phone,
            "time": extracted_time,
            "passenger_count": passengers,
            "is_package": is_package
        }
        
    # Aks holda AI ga beramiz
    return is_taxi_order_ai(text)

def is_taxi_order_ai(text: str) -> dict:
    """Sun'iy intellekt yordamida kichik joy nomlarini va qiyin gaplarni ajratish"""
    if not ai_clients:
        return {"is_taxi": False}
        
    prompt = f"""
    Sen foydalanuvchilarning xabarlarini tahlil qiluvchi AIsan.
    Foydalanuvchi xabari taksi qidirayotgan yoki taksi taklif qilayotgan e'lonmi? (Masalan, "O'rikzordan Chorsuga 2 ta odam bor").
    Agar bu salomlashish, reklama, haqorat, yoki taksiga umuman aloqasi yo'q xabar bo'lsa, is_taxi=false qaytar.
    Agar is_taxi=true bo'lsa, xabardan quyidagi ma'lumotlarni ajratib ol:
    - from_location: Qayerdan ketishi (agar aniq bo'lmasa "Noma'lum")
    - to_location: Qayerga borishi (agar aniq bo'lmasa "Noma'lum")
    - time: Vaqti (agar aniq bo'lmasa "Noma'lum")
    - passenger_count: Necha kishi (agar aniq bo'lmasa "Noma'lum")
    - is_package: Agar posilka (pochta) bo'lsa true, aks holda false
    - phone_number: Telefon raqami (agar xabarda yozilmagan bo'lsa "Xabarning o'zida")
    - price: Narxi (agar aniq bo'lmasa "Kelishiladi")
    
    Faqat JSON formatida javob ber.
    Xabar: {text}
    """
    
    attempts = len(ai_clients)
    for attempt in range(attempts):
        client = get_current_client()
        if not client:
            break
        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema={
                        "type": "OBJECT",
                        "properties": {
                            "is_taxi": {"type": "BOOLEAN"},
                            "from_location": {"type": "STRING"},
                            "to_location": {"type": "STRING"},
                            "time": {"type": "STRING"},
                            "passenger_count": {"type": "STRING"},
                            "is_package": {"type": "BOOLEAN"},
                            "phone_number": {"type": "STRING"},
                            "price": {"type": "STRING"}
                        },
                        "required": ["is_taxi"]
                    }
                )
            )
            data = json.loads(response.text)
            
            # AI ma'lumot qaytarsa, route_key ni ulab qo'yamiz
            if data.get("is_taxi"):
                from_l = data.get("from_location", "").lower()
                to_l = data.get("to_location", "").lower()
                if from_l and to_l and from_l != "noma'lum":
                    data["route"] = f"{from_l}-{to_l}"
                else:
                    data["route"] = "Noma'lum"
            
            return data
        except Exception as e:
            logging.warning(f"AI Call Xatolik (Key #{_current_client_index + 1}): {e}. Zaxira API keyga o'tilmoqda...")
            rotate_client()

    return {"is_taxi": False}
