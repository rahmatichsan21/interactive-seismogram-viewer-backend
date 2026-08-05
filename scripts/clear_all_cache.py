import os
import glob
from app.core.database import SessionLocal
from app.models.waveform import WaveformRecord

def run_full_cleanup():
    db = SessionLocal()
    
    # 1. Ambil semua data dari database
    records = db.query(WaveformRecord).all()
    print(f"[*] Menemukan {len(records)} data cache di database. Memulai proses penghapusan...")
    
    # 2. Hapus file fisiknya satu per satu
    for record in records:
        if record.file_path and os.path.exists(record.file_path):
            try:
                os.remove(record.file_path)
            except Exception as e:
                print(f"[-] Gagal menghapus file {record.file_path}: {e}")
    
    # 3. Hapus semua file .mseed yang mungkin "nyangkut" (orphaned files) di folder storage
    # Sesuaikan path "storage/waveforms" jika folder Anda berbeda
    orphaned_files = glob.glob(os.path.join("storage", "waveforms", "*.mseed"))
    for file in orphaned_files:
        try:
            os.remove(file)
        except Exception as e:
            pass # Abaikan jika sudah terhapus di langkah sebelumnya
            
    print("[+] Semua file fisik berhasil dibersihkan dari hard disk.")

    # 4. Hapus seluruh baris di database
    deleted_count = db.query(WaveformRecord).delete()
    db.commit()
    print(f"[+] Berhasil menghapus {deleted_count} baris dari database.")
    
    print("[*] Sapu bersih selesai! Cache sekarang kembali perawan.")
    db.close()

if __name__ == "__main__":
    run_full_cleanup()