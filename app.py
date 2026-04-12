import os
import time
import logging
import requests
import concurrent.futures
import streamlit as st
import gc
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from weasyprint import HTML

# הגדרות תצוגה של Streamlit
st.set_page_config(page_title="הורדת ספרי חב\"ד", page_icon="📚", layout="centered")

# השתקת הודעות מערכת מיותרות
logging.getLogger('fontTools').setLevel(logging.WARNING)
logging.getLogger('weasyprint').setLevel(logging.WARNING)

def get_manuscript_metadata(ms_id):
    url = f"https://chabadlibrary.org/catalog/index1.php?frame=main&catalog=mscatalog&mode=details&volno={ms_id}&limit=0&search_mode=simple"
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')
    
    lines = soup.get_text(separator='\n', strip=True).split('\n')
    metadata = {"מספר כתב יד": str(ms_id), "מדור ומדף": "", "תיאור": []}
    
    for line in lines:
        line = line.strip()
        if not line or "קטלוג ספריית" in line or "לתצלום הספר" in line or "chabadlibrary.org" in line:
            continue
        if "מדור ומדף:" in line:
            metadata["מדור ומדף"] = line.split("מדור ומדף:")[1].strip()
            continue
        if line.startswith("מס' כרטיס"):
            continue
        metadata["תיאור"].append(line)
        
    return metadata

def create_cover_page_html(metadata, output_filename):
    desc_html = "".join([f"<p>{line}</p>" for line in metadata['תיאור']])
    html_content = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="he">
    <head>
        <meta charset="utf-8">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@400;700&display=swap');
            body {{ font-family: 'Frank Ruhl Libre', serif; text-align: center; padding-top: 120px; color: #000; }}
            h1 {{ font-size: 50px; margin-bottom: 20px; }}
            h2 {{ font-size: 30px; margin-bottom: 70px; font-weight: normal; }}
            .description {{ font-size: 24px; line-height: 1.8; }}
            p {{ margin: 8px 0; }}
        </style>
    </head>
    <body>
        <h1>כתב יד מספר {metadata['מספר כתב יד']}</h1>
        <h2>מדור ומדף: {metadata['מדור ומדף']}</h2>
        <div class="description">{desc_html}</div>
    </body>
    </html>
    """
    HTML(string=html_content).write_pdf(output_filename)

def download_single_page(page_num, base_url, max_retries=3):
    url = f"{base_url}{page_num}.pdf"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                return page_num, response.content, 200
            elif response.status_code == 404:
                return page_num, None, 404
            else:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return page_num, None, response.status_code
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return page_num, None, str(e)

st.title("📚 הורדת כתבי יד - ספריית חב\"ד")
st.markdown("הכנס את מספר כתב היד כפי שהוא מופיע בקטלוג, והמערכת תייצר עבורך קובץ PDF שלם להורדה.")

ms_id_input = st.text_input("הכנס מספר כתב יד (למשל: 1102):")
start_button = st.button("הכן ספר להורדה", type="primary")

if start_button and ms_id_input:
    ms_id = ms_id_input.strip()
    
    with st.spinner('אוסף נתונים ובונה דף שער...'):
        start_time = time.time() 
        metadata = get_manuscript_metadata(ms_id)
        cover_pdf = f"cover_page_{ms_id}.pdf"
        create_cover_page_html(metadata, cover_pdf)
        
        base_url = f"https://s3.wasabisys.com/chabadlibrary/ms/{ms_id}/{ms_id}_page_"
        
        chunk_files = [cover_pdf] 
        current_page = 1
        keep_downloading = True
        download_batch_size = 25 
        
    status_text = st.empty()
    progress_bar = st.progress(0)
    
    while keep_downloading:
        status_text.info(f"מוריד ומעבד עמודים {current_page} עד {current_page + download_batch_size - 1}...")
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=download_batch_size) as executor:
            futures = {executor.submit(download_single_page, p, base_url): p for p in range(current_page, current_page + download_batch_size)}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        
        results.sort(key=lambda x: x[0]) 
        
        chunk_merger = PdfWriter()
        temp_single_pages = []
        
        for page_num, content, status in results:
            if content is None:
                if status == 404:
                    status_text.success(f"הגענו לסוף הספר (סה\"כ {page_num - 1} עמודים). אורז קובץ סופי...")
                else:
                    st.error(f"⚠️ שגיאה בעמוד {page_num}: {status}")
                keep_downloading = False
                break 
            
            temp_pdf = f"temp_page_{page_num}_{ms_id}.pdf"
            with open(temp_pdf, 'wb') as f:
                f.write(content)
            
            chunk_merger.append(temp_pdf)
            temp_single_pages.append(temp_pdf)
        
        if temp_single_pages:
            chunk_filename = f"chunk_{current_page}_to_{current_page + len(temp_single_pages) - 1}_{ms_id}.pdf"
            chunk_merger.write(chunk_filename)
            chunk_files.append(chunk_filename)
        
        chunk_merger.close()
        
        for temp_pdf in temp_single_pages:
            if os.path.exists(temp_pdf): os.remove(temp_pdf)
            
        gc.collect() 
        
        current_page += download_batch_size
        progress_bar.progress(min(current_page / 1000, 1.0)) 
        
        if keep_downloading:
            time.sleep(1.5)

    status_text.info("מחבר את כל המקבצים לספר שלם, אנא המתן...")
    final_merger = PdfWriter()
    for chunk_file in chunk_files:
        final_merger.append(chunk_file)
        
    final_output = f"Manuscript_{ms_id}_Complete.pdf"
    final_merger.write(final_output)
    final_merger.close()
    
    for chunk_file in chunk_files:
        if os.path.exists(chunk_file): os.remove(chunk_file)
    gc.collect()
            
    total_time = round(time.time() - start_time, 2)
    progress_bar.empty()
    status_text.empty()
    st.success(f"✅ הספר {ms_id} מוכן! (זמן בנייה: {total_time} שניות)")
    
    with open(final_output, "rb") as pdf_file:
        PDFbyte = pdf_file.read()
        st.download_button(
            label="📥 לחץ כאן להורדת ה-PDF השלם",
            data=PDFbyte,
            file_name=final_output,
            mime='application/octet-stream'
        )
    
    if os.path.exists(final_output): os.remove(final_output)
