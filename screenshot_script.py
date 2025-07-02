from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from PIL import Image
import time

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1-lZe2iqBUesOMjYx2Lk4VMiWbjq3wyo3JEHWYBp1GZI"

options = webdriver.ChromeOptions()
options.add_argument("--headless")
options.add_argument("--no-sandbox")  
options.add_argument("--disable-dev-shm-usage")  
options.add_argument("--window-size=1920,1080") 
options.binary_location = "/nix/store/zi4f80l169xlmivz8vja8wlphq74qqk0-chromium-125.0.6422.141/bin/chromium"

driver = webdriver.Chrome(service=Service(
    "/nix/store/3qnxr5x6gw3k9a9i7d0akz0m6bksbwff-chromedriver-125.0.6422.141/bin/chromedriver"
),
                          options=options)


driver.get(SPREADSHEET_URL)
time.sleep(5)  

table_element = driver.find_element(
    By.XPATH,
    "//div[contains(@class, 'grid-container')]")  

full_screenshot_path = "/tmp/full_spreadsheet.png"
driver.save_screenshot(full_screenshot_path)

location = table_element.location
size = table_element.size
x, y = location["x"], location["y"]
width, height = size["width"], size["height"]

crop_x_left = x + 52  
crop_y_top = y + 25  
crop_x_right = x + width - 272  
crop_y_bottom = y + height - 270  

image = Image.open(full_screenshot_path)
cropped_image = image.crop(
    (crop_x_left, crop_y_top, crop_x_right, crop_y_bottom))

cropped_screenshot_path = "/tmp/spreadsheet_final.png"
cropped_image.save(cropped_screenshot_path)
print(f"✅ Final Cropped Screenshot saved as {cropped_screenshot_path}")

driver.quit()
