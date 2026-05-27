import requests
from bs4 import BeautifulSoup

headers = {'User-Agent': 'Quant Terminal meet.singh@example.com'}
url = "https://www.sec.gov/Archives/edgar/data/21344/000162828026028802/ko-20260403.htm"

r = requests.get(url, headers=headers)
soup = BeautifulSoup(r.text, 'html.parser')

print("Searching for Consolidated Statements of Income...")
# Find the text "CONSOLIDATED STATEMENTS OF INCOME"
tables = soup.find_all('table')

for table in tables:
    text = table.get_text(separator=' ', strip=True).upper()
    if 'CONSOLIDATED STATEMENTS OF INCOME' in text or 'STATEMENTS OF INCOME' in text or 'NET OPERATING REVENUES' in text:
        # We found a potential income statement table
        if 'NET OPERATING REVENUES' in text:
            print("\nFound Income Statement Table. Extracting rows:")
            rows = table.find_all('tr')
            for row in rows[:20]: # just the top part where revenue is
                cols = row.find_all(['td', 'th'])
                row_text = []
                for c in cols:
                    t = c.get_text(strip=True)
                    if t:
                        row_text.append(t)
                
                if row_text:
                    print(" | ".join(row_text))
            
            print("\nFinished parsing table.")
            break
