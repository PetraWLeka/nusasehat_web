"""
Management command: seed_crops
Seeds the CropRecommendation table with Indonesian crop data.
"""

from django.core.management.base import BaseCommand

from nutrition.models import CropRecommendation


CROP_DATA = [
    {
        "name": "Bayam (Spinach)",
        "scientific_name": "Amaranthus spp.",
        "emoji": "🥬",
        "nutritional_benefits": "Zat besi: 2.7mg/100g, Vitamin A: 469μg, Kalsium: 99mg, Vitamin C: 28mg. Sangat baik untuk pencegahan anemia.",
        "stunting_relevance": "Tinggi zat besi dan kalsium untuk pertumbuhan tulang dan pencegahan anemia pada anak.",
        "planting_guide": "Tanam benih langsung di lahan. Jarak tanam 15-20cm. Siram rutin pagi dan sore. Panen 25-30 hari setelah tanam.",
        "harvest_time": "25-30 hari",
        "compatible_climates": ["tropis", "subtropis"],
        "compatible_soils": ["lempung", "berpasir"],
    },
    {
        "name": "Kangkung (Water Spinach)",
        "scientific_name": "Ipomoea aquatica",
        "emoji": "🌿",
        "nutritional_benefits": "Vitamin A: 315μg/100g, Vitamin C: 55mg, Zat besi: 1.67mg. Mudah ditanam di dataran rendah.",
        "stunting_relevance": "Sumber vitamin A dan C murah yang mudah diakses masyarakat untuk imunitas anak.",
        "planting_guide": "Tanam stek batang di lahan basah atau pot dengan air. Panen 25-30 hari.",
        "harvest_time": "25-30 hari",
        "compatible_climates": ["tropis"],
        "compatible_soils": ["lempung", "berair"],
    },
    {
        "name": "Kelor (Moringa)",
        "scientific_name": "Moringa oleifera",
        "emoji": "🌳",
        "nutritional_benefits": "Protein: 9.4g/100g, Kalsium: 185mg, Vitamin A: 378μg, Vitamin C: 51.7mg. Superfood lokal, 7x vitamin C jeruk, 4x kalsium susu.",
        "stunting_relevance": "Anti-stunting terbaik! Protein tinggi untuk pertumbuhan otot, kalsium untuk tulang, zat besi untuk darah.",
        "planting_guide": "Tanam biji atau stek. Tumbuh cepat di dataran rendah. Panen daun setelah 2 bulan.",
        "harvest_time": "60 hari (daun pertama)",
        "compatible_climates": ["tropis", "kering"],
        "compatible_soils": ["lempung", "berpasir", "berbatu"],
    },
    {
        "name": "Ubi Jalar Oranye (Orange Sweet Potato)",
        "scientific_name": "Ipomoea batatas",
        "emoji": "🍠",
        "nutritional_benefits": "Beta-karoten: 8509μg/100g, Karbohidrat: 20g, Serat: 3g, Vitamin C: 2.4mg.",
        "stunting_relevance": "Sumber karbohidrat dan beta-karoten tinggi. Penting untuk kesehatan mata anak.",
        "planting_guide": "Tanam stek batang di guludan tanah. Jarak tanam 25-30cm. Panen 3.5-4 bulan.",
        "harvest_time": "3.5-4 bulan",
        "compatible_climates": ["tropis"],
        "compatible_soils": ["berpasir", "lempung"],
    },
    {
        "name": "Kacang Tanah (Peanut)",
        "scientific_name": "Arachis hypogaea",
        "emoji": "🥜",
        "nutritional_benefits": "Protein: 25.8g/100g, Lemak sehat: 49.2g, Zat besi: 4.6mg, Zinc: 3.3mg.",
        "stunting_relevance": "Sumber protein nabati dan lemak sehat. Zinc penting untuk tumbuh kembang anak.",
        "planting_guide": "Tanam biji di tanah gembur. Jarak 20x30cm. Panen 90-100 hari.",
        "harvest_time": "90-100 hari",
        "compatible_climates": ["tropis"],
        "compatible_soils": ["berpasir", "lempung"],
    },
    {
        "name": "Pepaya (Papaya)",
        "scientific_name": "Carica papaya",
        "emoji": "🍈",
        "nutritional_benefits": "Vitamin C: 60.9mg/100g, Vitamin A: 47μg, Serat: 1.7g, Folat: 37μg.",
        "stunting_relevance": "Buah tropis kaya vitamin C dan enzim papain untuk pencernaan, meningkatkan penyerapan nutrisi.",
        "planting_guide": "Tanam biji di polybag lalu pindah ke lahan. Berbuah 8-10 bulan.",
        "harvest_time": "8-10 bulan",
        "compatible_climates": ["tropis"],
        "compatible_soils": ["lempung"],
    },
    {
        "name": "Tomat (Tomato)",
        "scientific_name": "Solanum lycopersicum",
        "emoji": "🍅",
        "nutritional_benefits": "Vitamin C: 14mg/100g, Likopen: 2573μg, Vitamin A: 42μg, Kalium: 237mg.",
        "stunting_relevance": "Sumber likopen dan vitamin C untuk imunitas tubuh anak.",
        "planting_guide": "Semai benih, pindah tanam setelah 3 minggu. Beri ajir. Panen 60-70 hari.",
        "harvest_time": "60-70 hari",
        "compatible_climates": ["tropis", "subtropis"],
        "compatible_soils": ["lempung"],
    },
    {
        "name": "Temulawak (Javanese Turmeric)",
        "scientific_name": "Curcuma zanthorrhiza",
        "emoji": "🌾",
        "nutritional_benefits": "Kurkuminoid: 1-2%, Minyak atsiri, Pati, Antioksidan tinggi.",
        "stunting_relevance": "Tanaman herbal tradisional untuk kesehatan pencernaan, meningkatkan nafsu makan anak.",
        "planting_guide": "Tanam rimpang di tanah gembur berhumus. Panen 8-12 bulan.",
        "harvest_time": "8-12 bulan",
        "compatible_climates": ["tropis"],
        "compatible_soils": ["lempung"],
    },
]


class Command(BaseCommand):
    help = "Seed the database with Indonesian crop recommendations"

    def handle(self, *args, **options):
        created_count = 0
        for crop in CROP_DATA:
            _, created = CropRecommendation.objects.get_or_create(
                name=crop["name"],
                defaults=crop,
            )
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_count} new crop recommendations "
                f"({CropRecommendation.objects.count()} total)"
            )
        )
