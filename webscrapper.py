#Web-scrapping Imports
from flask import Flask, request, jsonify, Response
from flask_executor import Executor
from bs4 import BeautifulSoup
from fpdf import FPDF, XPos, YPos
import concurrent.futures
import time
import re
import requests
import os
from urllib.parse import urljoin, urlparse
import fitz
import warnings
from cryptography.utils import CryptographyDeprecationWarning
import aiohttp
import asyncio

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

app = Flask(__name__)  

#web scraper
class WebScraper:
    def __init__(self, base_url):
        self.base_url = base_url
        self.visited_urls = set()
        self.to_visit_urls = set([base_url])
        self.scraped_content = []
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    

    def scrape(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            while self.to_visit_urls:
                futures = {executor.submit(self.scrape_url, url): url for url in self.to_visit_urls}
                self.to_visit_urls = set()
                for future in concurrent.futures.as_completed(futures):
                    new_urls = future.result()
                    if new_urls:
                        self.to_visit_urls.update(new_urls)
                self.to_visit_urls -= self.visited_urls

    def scrape_url(self, url):
        if url in self.visited_urls:
            return set()
        print(f"Scraping: {url}")
        self.visited_urls.add(url)

        for attempt in range(3):  # Retry mechanism
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                break
            except requests.RequestException as e:
                print(f"Error scraping {url} (attempt {attempt + 1}): {e}")
                if attempt == 2:  # If the last attempt fails, return an empty set
                    return set()
                time.sleep(2)  # Wait before retrying

        try:
            soup = BeautifulSoup(response.text, 'lxml')
            if "Cloudflare" in soup.text:
                print(f"Skipping Cloudflare protected content at {url}")
                return set()
            self.extract_content(soup, url)
        except Exception as e:
            print(f"Error parsing content from {url}: {e}")
            return set()

        new_urls = set()
        for link in soup.find_all('a', href=True):
            new_url = urljoin(url, link['href'])
            if self.is_valid_url(new_url) and new_url not in self.visited_urls:
                new_urls.add(new_url)
        return new_urls

    def extract_content(self, soup, url):
        # Define a broader set of tags to look for
        common_tags = ['article', 'section', 'div', 'pre', 'code', 'p', 'li', 'h1', 'h2', 'h3']
        content_list = []

        # Extract content from common tags
        for tag in common_tags:
            for element in soup.find_all(tag):
                text = element.get_text(separator="\n", strip=True)
                if text:
                    content_list.append(text)

        # If no content found in specific tags, extract all text
        if not content_list:
            all_text = soup.get_text(separator="\n", strip=True)
            content_list.append(all_text)

        # Combine all extracted content
        combined_content = "\n\n".join(content_list)

        # Clean the combined content
        cleaned_content = self.clean_text(combined_content)

        if cleaned_content.strip():
            self.scraped_content.append({"url": url, "content": cleaned_content})
        else:
            print(f"No meaningful content found at {url}")

    def clean_text(self, text):
        # Implement any cleaning logic here, e.g., removing unnecessary lines
        return "\n".join(line for line in text.splitlines() if len(line.strip()) > 0)

    def download_video(self, video_url):
        local_filename = video_url.split('/')[-1]
        try:
            with requests.get(video_url, stream=True) as r:
                r.raise_for_status()
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print(f"Downloaded video: {local_filename}")
        except Exception as e:
            print(f"Error downloading video {video_url}: {e}")

    def save_to_pdf(self, pdf_file):
        pdf = FPDF()
        pdf.add_page()

        # Define emoji detection pattern
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
            "]+", flags=re.UNICODE)

        # Add Unicode font (DejaVuSans)
        pdf.add_font('DejaVuSans', '', 'dejavu/DejaVuSans-Oblique.ttf')
        pdf.add_font('NotoColorEmoji', '', 'notcolor/NotoColorEmoji-Regular.ttf')

        if not self.scraped_content:
            print("No content to save. The scraped_content list is empty.")
        else:
            for entry in self.scraped_content:
                pdf.set_font("DejaVuSans", size=12)
                pdf.multi_cell(0, 10, f"Scraped content from: {entry['url']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                content = entry['content']
                content_parts = re.split(emoji_pattern, content)
                emojis = emoji_pattern.findall(content)

                for i, part in enumerate(content_parts):
                    if part:
                        pdf.set_font("DejaVuSans", size=12)
                        try:
                            # Attempt to write the content with the full width
                            pdf.multi_cell(0, 10, part, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        except Exception as e:
                            print(f"Error writing text to PDF: {e}")

                    if i < len(emojis):
                        pdf.set_font("NotoColorEmoji", size=12)
                        try:
                            pdf.multi_cell(0, 10, emojis[i], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        except Exception as e:
                            print(f"Error writing emoji to PDF: {e}")

                # Separator line after each URL content
                pdf.set_font("DejaVuSans", size=12)
                pdf.multi_cell(0, 10, f"\n{'='*80}\n\n", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.output(pdf_file)

    def is_valid_url(self, url):
        parsed_url = urlparse(url)
        return parsed_url.netloc == urlparse(self.base_url).netloc

def compress_pdf(input_file, output_file, quality=30):
    doc = fitz.open(input_file)
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        image_list = page.get_images(full=True)
        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]

            # Compress the image
            compressed_image = fitz.Pixmap(fitz.csRGB, fitz.open("png", image_bytes), alpha=False)
            compressed_image = fitz.Pixmap(compressed_image, 0)  # Drop alpha channel
            compressed_image.save(f"compressed_img_{img_index}.png", quality=quality)

            # Replace the image in the PDF
            rect = page.get_image_rects(xref)[0]
            page.insert_image(rect, filename=f"compressed_img_{img_index}.png")
            os.remove(f"compressed_img_{img_index}.png")

    doc.save(output_file, garbage=4, deflate=True)
    doc.close()

def run_scraping_task(url, ssa, site_id, domain_name):
    # Determine the API URL based on the domain in the URL
    if domain_name == "website1.com":
        api_url = "your API URL with domain name"
    elif domain_name == "website2.com":
        api_url = "your API URL with domain name"
    else:
        return jsonify({"error": "Unsupported domain"}), 400

    token = "your_token"

    # Proceed with the scraping and uploading process
    scraper = WebScraper(url)
    scraper.scrape()
    original_pdf = "scraped_content.pdf"
    scraper.save_to_pdf(original_pdf)
    compressed_pdf = "compressed_document.pdf"
    compress_pdf(original_pdf, compressed_pdf)

    with open(compressed_pdf, 'rb') as f:
        files = {'files': f}
        data_payload = {'ssa': ssa, 'site_id': site_id}
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

        # Add logging for request details
        print(f"Uploading to {api_url} with headers: {headers} and payload: {data_payload}")

        response = requests.post(api_url, headers=headers, files=files, data=data_payload)

        # Log the response details
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Headers: {response.headers}")
        print(f"Response Body: {response.text}")

        if response.status_code != 200:
            print(f"Failed to upload PDF to {api_url}. Status code: {response.status_code}")
            return jsonify({"error": "Failed to upload PDF"}), response.status_code

        os.remove(original_pdf)
        return jsonify({
            "api_response": response.json() if response.content else "Empty response from API"
        })
@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    url = data.get('url')
    ssa = data.get('ssa')
    site_id = data.get('site_id')
    domain_name = data.get("domain_name")
    

    if not url or not ssa:
        return jsonify({"error": "URL and SSA are required"}), 400
    # If site_id is not provided, you can set it to None or handle it as needed
    if site_id is None:
        site_id = None  # or you can set it to a default value if needed
    # Start the scraping task in the background
    executor.submit(run_scraping_task, url, ssa, site_id, domain_name)

    

    return jsonify({
        "message": "Webpage is being processed. Scraping might take a while"
    })
if __name__ == "__main__":
    app.run(debug=True)
