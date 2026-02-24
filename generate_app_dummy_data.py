import os
import random
import sys
from datetime import timedelta
from django.utils import timezone

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nusahealth_cloud.settings")
    import django
    django.setup()

    from django.core.files.base import ContentFile
    from core.models import User
    from patients.models import Patient
    from consultations.models import ConsultationSession, ChatMessage

    print("Generating Dummy App Data...")

    # --- Generate Staff Users ---
    staff_names = ["Dr. Andi", "Ns. Budi", "Dr. Citra", "Bidan Dian"]
    staff_users = []
    for i, name in enumerate(staff_names):
        username = f"staff_{i+1}"
        user, created = User.objects.get_or_create(username=username, defaults={
            "full_name": name,
            "role": User.Role.STAFF,
            "email": f"{username}@nusahealth.id",
            "is_active_account": True,
        })
        if created:
            user.set_password("nusahealth123")
            user.save()
        staff_users.append(user)
    print(f"Created {len(staff_users)} staff users.")

    # --- Generate Patients ---
    patient_data = [
        {"name": "Bapak Agung", "gender": "L", "age": 45, "vill": "Desa Maju"},
        {"name": "Ibu Sari", "gender": "P", "age": 30, "vill": "Desa Sejahtera"},
        {"name": "Anak Budi", "gender": "L", "age": 4, "vill": "Desa Makmur"},
        {"name": "Kakek Tejo", "gender": "L", "age": 68, "vill": "Desa Damai"},
        {"name": "Mbak Lia", "gender": "P", "age": 25, "vill": "Desa Harapan"},
    ]
    
    # We will generate a simple placeholder image for patients using Pillow
    try:
        from PIL import Image, ImageDraw
        import io
        
        def create_placeholder_image(text):
            img = Image.new('RGB', (200, 200), color = (73, 109, 137))
            d = ImageDraw.Draw(img)
            d.text((50, 90), text, fill=(255, 255, 0))
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            return buf.getvalue()
    except ImportError:
        def create_placeholder_image(text):
            return b"dummy_image_data"

    patients = []
    for p in patient_data:
        dob = timezone.now() - timedelta(days=p["age"] * 365)
        patient, created = Patient.objects.get_or_create(
            full_name=p["name"],
            defaults={
                "nik": f"320000{random.randint(1000000000, 9999999999)}",
                "date_of_birth": dob.date(),
                "gender": p["gender"],
                "village": p["vill"],
                "created_by": staff_users[0],
                "status": Patient.Status.STABLE
            }
        )
        if created:
            image_data = create_placeholder_image(p["name"])
            patient.photo.save(f"dummy_{patient.pk}.jpg", ContentFile(image_data), save=True)
            print(f"Created patient {patient.full_name} with dummy image.")
        patients.append(patient)
    
    # --- Generate Chats ---
    # Scenarios for chats: 
    # 1. Finished chat -> triggers illness & item increment
    # 2. Unfinished chat -> is_active = True
    
    # Asumsi array 'patients' sudah didefinisikan sebelumnya di kode Anda.
# patients = [patient1, patient2, patient3, patient4, patient5, patient6, patient7, patient8]

    # Asumsi array 'patients' sudah didefinisikan sebelumnya di kode Anda.
# patients = [patient1, patient2, patient3, patient4, patient5, patient6]

    scenarios = [
        {
            "patient": patients[0], 
            "status": "finished", 
            "illness": "Demam Berdarah Dengue (DBD)", 
            "items": ["Infus Ringer Laktat", "RDT Dengue", "Paracetamol"],
            "messages": [
                ("user", "Dok, pasien datang dengan keluhan demam tinggi mendadak sejak 3 hari lalu. Suhu 39.5°C, ada nyeri sendi, sakit kepala belakang mata, dan mual hebat."),
                ("ai_4b", " Berdasarkan gejala demam akut mendadak, myalgia (nyeri sendi), dan nyeri retro-orbital yang Anda sebutkan, ini merupakan trias klasik yang sangat mengarah pada infeksi Arbovirus, khususnya Dengue.\n\nMengingat data Open-Meteo menunjukkan curah hujan tinggi di wilayah Anda selama 2 minggu terakhir, kewaspadaan terhadap DBD harus ditingkatkan. Mohon lakukan pengecekan berikut:\n1. Tanda-tanda vital lengkap (Tensi, Nadi, Laju Napas).\n2. Lakukan uji bendung (Tourniquet Test).\n3. Periksa apakah ada manifestasi perdarahan spontan seperti gusi berdarah, mimisan, atau bintik merah (petechiae) di kulit?"),
                ("user", "Ada bintik merah sedikit di area lengan dalam. Hasil tes Tourniquet positif. Tensi 100/70, Nadi 98x/menit."),
                ("ai_27b", " **Diagnosis: Suspek Demam Berdarah Dengue (DBD) Derajat I/II**\n\nBerdasarkan pedoman PNPK Kemenkes RI, kombinasi demam akut, uji tourniquet positif, dan petechiae mengkonfirmasi diagnosis klinis ini. Pasien berada pada fase kritis (hari ke-3 hingga ke-5) di mana kebocoran plasma berisiko terjadi.\n\n**Tindakan & Rencana Terapi:**\n* **Resusitasi Cairan:** Segera pasang jalur IV. Berikan cairan kristaloid (Infus Ringer Laktat) untuk pemeliharaan hidrasi dan mencegah syok hipovolemik.\n* **Simptomatik:** Berikan Paracetamol untuk menurunkan demam. **Peringatan Keras:** Hindari pemberian obat golongan NSAID (seperti Ibuprofen atau Aspirin) karena dapat memperparah perdarahan lambung.\n* **Diagnostik:** Lakukan pemeriksaan RDT Dengue (NS1/IgG/IgM) dan cek Darah Lengkap (fokus pada penurunan Trombosit dan peningkatan Hematokrit).\n* **Observasi:** Pantau ketat *urine output* (jumlah kencing) dan tanda vital setiap 4 jam.\n\n*Logistik (RDT Dengue, RL, Paracetamol) telah ditambahkan ke sistem inventaris untuk pasien ini.*")
            ]
        },
        {
            "patient": patients[1], 
            "status": "finished", 
            "illness": "Kehamilan Trimester 1 (Emesis)", 
            "items": ["Asam Folat", "Vitamin B6", "Partus Set (Jadwal)"],
            "messages": [
                ("user", "Pasien ibu hamil (G1P0A0), usia kehamilan 8 minggu. Mengeluh mual muntah setiap pagi, badan terasa lemas tapi masih bisa minum air."),
                ("ai_4b", " Mencatat data: Kehamilan Trimester 1 dengan keluhan Emesis Gravidarum (mual muntah kehamilan). \n\nUntuk memastikan ini bukan kondisi berbahaya (Hiperemesis Gravidarum), mohon konfirmasi beberapa parameter hidrasi pasien:\n1. Berapa kali pasien muntah dalam 24 jam terakhir?\n2. Apakah ada penurunan berat badan yang drastis (lebih dari 5% dari BB awal)?\n3. Bagaimana warna urin pasien (kuning jernih atau sangat pekat)?\n4. Berapa tekanan darah pasien saat ini?"),
                ("user", "Tensi normal 110/70. Muntah sekitar 2-3 kali sehari, tidak ada darah. Berat badan turun 1 kg. Urin masih kuning jernih."),
                ("ai_27b", " 📋 **Diagnosis: Emesis Gravidarum Ringan (Fisiologis)**\n\nKondisi hemodinamik pasien stabil dan tidak ada tanda dehidrasi berat. Ini adalah keluhan fisiologis yang sangat wajar terjadi pada trimester pertama akibat lonjakan hormon hCG.\n\n**Rencana Penatalaksanaan:**\n* **Farmakologi:** Berikan Vitamin B6 (Pyridoxine) 10-25 mg setiap 8 jam untuk meredakan mual. \n* **Suplemen Esensial:** Berikan Asam Folat (minimal 400 mcg/hari). Jelaskan kepada ibu bahwa suplemen ini sangat krusial di usia 8 minggu untuk mencegah cacat tabung saraf (Neural Tube Defect) pada janin.\n* **Edukasi Gizi:** Sarankan pasien untuk makan dengan porsi kecil tapi sering (makan sedikit-sedikit tiap 2 jam), hindari makanan berlemak tinggi atau berbau menyengat, dan sediakan biskuit kering di pagi hari sebelum bangun dari tempat tidur.\n\n*Sistem ERP Terjadwal: Mengaktifkan protokol kehamilan. Sistem akan otomatis memasukkan kebutuhan 'Tablet Tambah Darah (Fe)' untuk bulan depan, dan memproyeksikan kebutuhan 'Partus Set' untuk persiapan persalinan 7 bulan dari sekarang.*")
            ]
        },
        {
            "patient": patients[2], 
            "status": "finished", 
            "illness": "Stunting & Kecacingan", 
            "items": ["Albendazole", "Zinc", "Paket PMT (Telur)"],
            "messages": [
                ("user", "Anak laki-laki usia 24 bulan, berat badan hanya 9 kg, tinggi badan 78 cm. Ibu mengeluh anak sangat susah makan dan sering lesu."),
                ("ai_4b", " ⚠️ **Peringatan Deteksi Dini:** Berdasarkan kurva pertumbuhan WHO (TB/U), Z-Score anak ini berada di bawah -2.0 SD, yang masuk dalam kategori **Stunting**.\n\nMasalah nafsu makan dan kelesuan bisa jadi memiliki penyebab penyerta. Tolong tanyakan kepada ibu pasien:\n1. Apakah anak sering mengalami diare kronis atau feses berlendir?\n2. Apakah anak terlihat pucat pada bagian dalam kelopak mata atau telapak tangan?\n3. Apakah anak sering menggaruk area dubur, terutama di malam hari?"),
                ("user", "Iya, perutnya memang sering buncit dan bulan lalu sempat diare lama. Kata ibunya, anaknya sering garuk-garuk pantat kalau malam hari dan susah tidur."),
                ("ai_27b", " 📋 **Diagnosis: Stunting dengan Suspek Helminthiasis (Kecacingan)**\n\nKeluhan pruritus ani (gatal di dubur malam hari), perut buncit, dan riwayat diare sangat mengindikasikan infeksi cacing (kemungkinan Enterobius vermicularis atau Ascaris). Infeksi cacing ini merampas nutrisi anak dan menyebabkan malabsorpsi, yang memperburuk kondisi stuntingnya.\n\n**Intervensi Medis & Gizi:**\n* **Pemberantasan Infeksi:** Berikan Albendazole 400mg dosis tunggal (karena anak sudah berusia >12 bulan). Obati juga seluruh anggota keluarga serumah untuk mencegah reinfeksi.\n* **Pemulihan Usus:** Berikan suplementasi Zinc selama 10-14 hari berturut-turut untuk memperbaiki mukosa usus pasca diare kronis.\n* **Intervensi Gizi (Kemenkes):** Segera daftarkan anak ini ke program Pemberian Makanan Tambahan (PMT). Edukasi ibu menggunakan modul 'Isi Piringku': Anak wajib mendapat asupan **Protein Hewani (1 butir telur sehari)**.\n* **Edukasi Sanitasi:** Tekankan pentingnya Cuci Tangan Pakai Sabun (CTPS) dan merebus air minum hingga mendidih, sesuai pedoman STBM.\n\n*Logistik (Albendazole, Zinc, Paket PMT) telah ditambahkan ke data pengeluaran Puskesmas.*")
            ]
        },
        {
            "patient": patients[3], 
            "status": "unfinished", 
            "illness": None, 
            "items": [],
            "messages": [
                ("user", "Pasien mengeluh batuk berdahak sudah lebih dari 3 minggu. Kadang malam hari sering berkeringat dingin walau tidak pakai selimut dan suhu ruangan biasa saja."),
                ("ai_4b", " 🚩 **Red Flag Warning!** Gejala batuk produktif (berdahak) yang persisten lebih dari 2 minggu yang disertai dengan keringat malam (night sweats) adalah tanda klasik yang sangat mencurigakan untuk Suspek Tuberkulosis (TBC) Paru.\n\nSebelum merujuk untuk pemeriksaan lab, tolong kumpulkan anamnesis tambahan:\n1. Apakah pasien mengalami penurunan berat badan yang drastis tanpa diet?\n2. Apakah dahak pernah bercampur darah (hemoptisis)?\n3. Apakah ada anggota keluarga atau tetangga dekat yang sedang menjalani pengobatan paru 6 bulan?\n4. Siapkan pot dahak, karena kita akan membutuhkan sampel dahak SPS (Sewaktu-Pagi-Sewaktu) untuk Tes Cepat Molekuler (TCM) atau pemeriksaan BTA."),
                ("user", "Iya, berat badannya turun drastis 4 kg dalam sebulan terakhir. Bajunya sampai kelonggaran. Tetangganya memang ada yang sedang pengobatan paru dari Puskesmas.")
            ]
        },
        {
            "patient": patients[4], 
            "status": "finished", 
            "illness": "Pneumonia Balita", 
            "items": ["Amoxicillin Sirup", "Paracetamol", "Oksigen (Logistik Rujukan)"],
            "messages": [
                ("user", "Anak usia 3 tahun batuk pilek sudah 4 hari. Hari ini napasnya terlihat sangat cepat dan ada tarikan dinding dada ke dalam (retraksi dada) saat menarik napas. Suhu 38.8°C."),
                ("ai_4b", " 🚨 **KODE MERAH - KEGAWATDARURATAN NAPAS**\n\nTarikan dinding dada bagian bawah ke dalam (chest indrawing) pada balita adalah 'Tanda Bahaya Umum' menurut pedoman MTBS (Manajemen Terpadu Balita Sakit) WHO. Ini menunjukkan anak kesulitan bernapas berat.\n\nSaya butuh parameter objektif sekarang juga:\n1. Hitung frekuensi napas (Respiration Rate) dalam 1 menit penuh saat anak sedang tenang!\n2. Cek saturasi oksigen (SpO2) menggunakan oximeter jika ada!\n3. Apakah ada tanda sianosis (bibir/kuku kebiruan) atau anak tampak sangat letih/tidak sadar?"),
                ("user", "Frekuensi napas 55 kali per menit, SpO2 92% di pulse oximeter. Anak tampak sangat lemas dan malas minum."),
                ("ai_27b", " 📋 **Diagnosis: PNEUMONIA BERAT**\n\nBatas pernapasan normal untuk anak usia 1-5 tahun adalah <40x/menit. Napas 55x/menit ditambah retraksi dada dan SpO2 <95% mengkonfirmasi Pneumonia Berat dengan hipoksia. Fasilitas tingkat pertama (Puskesmas) tidak memiliki ventilator memadai untuk menangani perburukan gagal napas ini.\n\n**Protokol Rujukan Segera (Cito!):**\n* **Terapi Oksigen:** Segera berikan oksigen aliran rendah (nasal cannula 1-2 liter/menit) untuk mempertahankan SpO2 >95%.\n* **Dosis Pra-Rujukan:** Berikan dosis pertama antibiotik spektrum luas segera (Amoxicillin sirup dosis tinggi atau injeksi Ampicillin/Gentamicin sesuai ketersediaan di IGD Puskesmas).\n* **Simptomatik:** Berikan Paracetamol sirup untuk menurunkan demam 38.8°C dan mencegah kejang demam.\n* **Tindakan Final:** Hubungi fasilitas rujukan (RSUD terdekat), siapkan ambulans darurat, dan pastikan jalan napas anak tetap terbuka selama perjalanan.\n\n*Penggunaan Oksigen Darurat dan Amoxicillin telah tercatat di sistem.*")
            ]
        },
        {
            "patient": patients[4], 
            "status": "unfinished", 
            "illness": None, 
            "items": [],
            "messages": [
                ("user", "Ada rombongan santri dari pesantren sebelah datang. Keluhannya seragam: gatal-gatal hebat di sela-sela jari tangan, pergelangan tangan, dan lipatan paha. Mereka bilang gatalnya sangat parah kalau malam hari sampai tidak bisa tidur."),
                ("ai_4b", " Analisis epidemiologis menunjukkan adanya wabah (cluster) di lingkungan padat penduduk (asrama/pesantren). Keluhan gatal di area predileksi (sela jari, lipatan paha) yang memburuk drastis di malam hari (pruritus nokturnal) adalah tanda patognomonik dari penyakit **Skabies (Kudis)** yang disebabkan oleh tungau *Sarcoptes scabiei*.\n\nSebelum AI 27B meresepkan Salep Permethrin massal, kita perlu konfirmasi klinis. \nApakah Anda ingin mengaktifkan **Modul Visual Laboratorium (MedGemma Vision)**? Silakan unggah foto jarak dekat (macro) dari sela-sela jari salah satu santri agar saya bisa mengidentifikasi keberadaan terowongan tungau (kunikulus) atau vesikel kemerahan di kulit mereka.")
            ]
        }
    ]

    import uuid
    
    # Get admin user so chats appear in admin's 'Konsultasi AI' tab
    admin_user = User.objects.filter(is_superuser=True).first() or User.objects.filter(username="admin").first() or staff_users[0]

    for sc in scenarios:
        # Append short UUID to prevent duplicate skipping
        short_hash = uuid.uuid4().hex[:4]
        title = f"Dummy Chat - {sc['patient'].full_name} ({short_hash})"

        session = ConsultationSession.objects.create(
            session_type=ConsultationSession.SessionType.STAFF,
            patient=sc["patient"],
            user=admin_user,
            title=title,
            is_active=(sc["status"] == "unfinished")
        )

        for sender, content in sc["messages"]:
            ChatMessage.objects.create(
                session=session,
                sender_type=sender,
                content=content,
                model_used="dummy-model-v1" if "ai" in sender else ""
            )
        
        if sc["status"] == "finished":
            session.ended_at = timezone.now()
            session.summary = f"Diagnosis: {sc['illness']}. Rekomendasi: {', '.join(sc['items'])}."
            session.save()
            print(f"Finished session for {sc['patient'].full_name}. (Skipping CSV logging as requested)")

    print("Dummy Data Generation Complete!")

if __name__ == "__main__":
    main()
