#!/bin/bash
# ============================================================
#  Taxi Bot — Linux serverga deploy skripti
#  Ubuntu/Debian uchun (Docker bilan)
# ============================================================

set -e

echo "=============================="
echo "  🚕 TAXI BOT DEPLOY SKRIPTI"
echo "=============================="

# --- 1. Docker o'rnatilganmi tekshirish ---
if ! command -v docker &> /dev/null; then
    echo "🔧 Docker o'rnatilmoqda..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "✅ Docker o'rnatildi. Iltimos, qayta login qiling va skriptni qayta ishga tushiring."
    exit 0
fi

# --- 2. Docker Compose o'rnatilganmi tekshirish ---
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    echo "🔧 Docker Compose o'rnatilmoqda..."
    sudo apt-get install -y docker-compose-plugin
fi

# --- 3. .env fayli bormi tekshirish ---
if [ ! -f ".env" ]; then
    echo "❌ .env fayli topilmadi!"
    echo "👇 Quyidagini bajaring:"
    echo "   cp .env.example .env"
    echo "   nano .env   (yoki vim .env)"
    echo ""
    echo "Va kerakli ma'lumotlarni to'ldiring, so'ng deploy.sh ni qayta ishga tushiring."
    exit 1
fi

# --- 4. Eski konteyner to'xtatish (agar mavjud bo'lsa) ---
echo "🛑 Eski konteyner to'xtatilmoqda (agar mavjud)..."
docker compose down 2>/dev/null || docker-compose down 2>/dev/null || true

# --- 5. Image build qilish ---
echo "🔨 Docker image build qilinmoqda..."
docker compose build --no-cache 2>/dev/null || docker-compose build --no-cache

# --- 6. Botni ishga tushirish ---
echo "🚀 Bot ishga tushirilmoqda..."
docker compose up -d 2>/dev/null || docker-compose up -d

# --- 7. Status tekshirish ---
sleep 3
echo ""
echo "📊 Konteyner holati:"
docker compose ps 2>/dev/null || docker-compose ps

echo ""
echo "📋 So'nggi loglar:"
docker compose logs --tail=20 2>/dev/null || docker-compose logs --tail=20

echo ""
echo "=============================="
echo "  ✅ DEPLOY MUVAFFAQIYATLI!"
echo "=============================="
echo ""
echo "Foydali buyruqlar:"
echo "  Loglarni ko'rish:      docker compose logs -f taxi-bot"
echo "  Botni to'xtatish:      docker compose stop"
echo "  Botni qayta yuklash:   docker compose restart"
echo "  Botni o'chirish:       docker compose down"
