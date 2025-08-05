
import requests
from bs4 import BeautifulSoup
from datetime import datetime

def get_forexfactory_bias():
    try:
        url = 'https://www.forexfactory.com/calendar'
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.content, 'html.parser')

        # Basic dummy logic for bias detection (can be expanded)
        events = soup.find_all('tr', class_='calendar__row')
        now = datetime.utcnow()
        for event in events:
            impact = event.find('td', class_='impact').get('title', '')
            title = event.find('td', class_='event').text.strip()
            if 'Fed' in title or 'CPI' in title:
                if 'High' in impact:
                    return "bearish" if 'rate hike' in title.lower() else "bullish"
        return "neutral"
    except:
        return "neutral"
    