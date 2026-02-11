# Import the Necessary Libraries
import socket
from PIL import Image, ImageDraw, ImageFont
import ST7789  # LCD Driver for Mini Pupper


# Connect to IP Address
def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.170.9.195", 8443))
        ip = s.getsockname()[0]
    except Exception:
        ip = "No Network"
    finally:
        s.close()
    return ip


# Display the IP Address on LCD Screen
def display_ip(ip):
    disp = ST7789.ST7789(
        # Dimensions in pixels (320px x 240px)
        height=240,
        width=320,

        # Flip the canvas vertically
        rotation=180,
        port=0,
        cs=ST7789.BG_SPI_CS_FRONT,
        dc=9,
        backlight=19,
        spi_speed_hz=80 * 1000 * 1000  # 80,000,000Hz
    )
    disp.begin()

    # Draw the image
    img = Image.new("RGB", (240, 240), color=(255, 255, 255))  # White background
    draw = ImageDraw.Draw(img)

    # Load a larger font (fallback to default if unavailable)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except:
        font = ImageFont.load_default()

    # Create the text to display
    text = f"IP: {ip}"

    # Calculate text size for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center text
    x = (240 - text_width) // 2
    y = (240 - text_height) // 2

    # Draw the text
    draw.text((x, y), text, font=font, fill=(0, 0, 0))  # Black text
    disp.display(img)

# Run the display
ip = get_ip_address()
display_ip(ip)
