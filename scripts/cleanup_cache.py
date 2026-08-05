import os
from app.core.database import SessionLocal
from app.models.waveform import WaveformRecord

def run_cleanup():
    db = SessionLocal()
    
    # Target spesifik ID 305 berdasarkan hasil diagnostik Anda
    target_id = 305
    record = db.query(WaveformRecord).filter(WaveformRecord.id == target_id).first()
    
    if record:
        file_path = record.file_path
        print(f"[*] Ditemukan record ID {target_id}.")
        print(f"[*] Target file: {file_path}")
        
        # 1. Hapus file fisik di hard disk
        if os.path.exists(file_path):
            os.remove(file_path)
            print("[+] File fisik berhasil dihapus dari storage.")
        else:
            print("[-] File fisik tidak ditemukan (mungkin sudah terhapus manual).")
            
        # 2. Hapus baris dari database
        db.delete(record)
        db.commit()
        print("[+] Record berhasil dihapus dari database.")
        
    else:
        print(f"[-] Record dengan ID {target_id} tidak ditemukan.")

    db.close()

if __name__ == "__main__":
    run_cleanup()