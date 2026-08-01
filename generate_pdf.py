import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas

# Custom Canvas for adding page numbers ("Page X of Y") and headers/footers
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        # Draw header and footer on all pages except the cover page
        if self._pageNumber > 1:
            # Running Header
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#0D9488")) # Teal / Emerald
            self.drawString(54, 750, "VELOLEADS — QUICK START USER GUIDE")
            
            # Header line
            self.setStrokeColor(colors.HexColor("#E2E8F0")) # Slate 200
            self.setLineWidth(0.75)
            self.line(54, 742, 558, 742)
            
            # Running Footer
            self.line(54, 55, 558, 55)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#64748B")) # Slate 500
            self.drawString(54, 40, "VeloLeads Lead Finder Application")
            self.drawRightString(558, 40, f"Page {self._pageNumber} of {page_count}")


def create_user_guide(output_path="VeloLeads_User_Guide.pdf"):
    print(f"[*] Starting PDF generation for '{output_path}'...")
    
    # 0.75 inch margins (54 points)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72
    )

    styles = getSampleStyleSheet()
    
    # Cohesive theme palette
    PRIMARY_COLOR = colors.HexColor("#0D9488")   # Teal/Emerald
    DARK_TEXT = colors.HexColor("#0F172A")       # Deep Slate
    BODY_TEXT = colors.HexColor("#334155")       # Slate Grey
    LIGHT_BG = colors.HexColor("#F8FAFC")        # Slate 50
    BORDER_COLOR = colors.HexColor("#E2E8F0")    # Slate 200

    # Custom Typography / Styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=28,
        leading=34,
        textColor=PRIMARY_COLOR,
        alignment=0,
        spaceAfter=8
    )

    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=13,
        leading=17,
        textColor=BODY_TEXT,
        alignment=0,
        spaceAfter=25
    )

    meta_label_style = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9.5,
        leading=14,
        textColor=DARK_TEXT
    )

    meta_val_style = ParagraphStyle(
        'MetaVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=BODY_TEXT
    )

    h1_style = ParagraphStyle(
        'Header1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=DARK_TEXT,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Header2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=DARK_TEXT,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=BODY_TEXT,
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14.5,
        textColor=BODY_TEXT,
        leftIndent=20,
        firstLineIndent=-10,
        spaceAfter=5
    )

    note_style = ParagraphStyle(
        'NoteText',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#0F766E"), # Dark Teal
        backColor=colors.HexColor("#F0FDFA"), # Light Teal
        borderColor=colors.HexColor("#CCFBF1"),
        borderWidth=0.75,
        borderPadding=8,
        spaceBefore=8,
        spaceAfter=8
    )

    story = []

    # ================= PAGE 1: COVER & QUICK INSTALL =================
    story.append(Spacer(1, 40))
    # Accent color bar
    logo_bar_data = [['']]
    logo_bar = Table(logo_bar_data, colWidths=[24], rowHeights=[6])
    logo_bar.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), PRIMARY_COLOR),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(logo_bar)
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("VeloLeads User Guide", title_style))
    story.append(Paragraph("Automated Lead Finder & Google Maps Scraper", subtitle_style))
    

    # Divider line
    story.append(Spacer(1, 10))
    divider_data = [['']]
    divider_table = Table(divider_data, colWidths=[504], rowHeights=[1])
    divider_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), BORDER_COLOR),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(divider_table)
    story.append(Spacer(1, 10))

    # Top Notices Box
    notice_text = (
        "<b>IMPORTANT NOTICE:</b><br/>"
        "1. You <b>must extract the ZIP file</b> completely before running the application. Do not run it from inside the ZIP view.<br/>"
        "2. <b>Copy the license key</b> once you have made the payment to activate the software."
    )
    story.append(Paragraph(notice_text, note_style))
    story.append(Spacer(1, 10))

    # Installation Section
    story.append(Paragraph("1. Easy Installation", h1_style))
    story.append(Paragraph(
        "VeloLeads is packaged as a standalone application. There is <b>no need to install Python</b> or configure environment variables.",
        body_style
    ))
    story.append(Paragraph("• <b>Extract files</b>: Extract the contents of the ZIP folder onto your computer.", bullet_style))
    story.append(Paragraph("• <b>Run the App (Windows)</b>: Double-click the <b>VeloLeads.exe</b> file to start the application.", bullet_style))
    story.append(Paragraph("• <b>Run the App (macOS)</b>: Double-click the <b>VeloLeads.app</b> file to start the application.", bullet_style))
    story.append(Paragraph("• <b>Auto-Setup</b>: On the first launch, the app automatically configures itself and installs background browser dependencies. This requires an active internet connection and takes about 30 seconds.", bullet_style))

    story.append(Paragraph("2. Activation & Licensing", h1_style))
    story.append(Paragraph(
        "When the app starts for the first time, you will see the Activation Screen:",
        body_style
    ))
    story.append(Paragraph("1. Enter your registered <b>Username / Email Address</b>.", bullet_style))
    story.append(Paragraph("2. Paste your 16-character <b>License Key</b>.", bullet_style))
    story.append(Paragraph("3. Click <b>Activate License</b>. The application will connect online to verify and register your device.", bullet_style))

    
    story.append(PageBreak())

    # ================= PAGE 2: SCRAPING STEPS & HELP =================
    story.append(Paragraph("3. How to Scrape Leads", h1_style))
    story.append(Paragraph(
        "The primary dashboard is the **Scraper** panel. Follow these simple steps to find new leads:",
        body_style
    ))

    # Steps Table
    steps_data = [
        [
            Paragraph("<b>Form Field</b>", meta_label_style),
            Paragraph("<b>What to Enter</b>", meta_label_style)
        ],
        [
            Paragraph("<b>Locations</b>", body_style),
            Paragraph("List of cities or regions separated by commas (e.g. <code>Hyderabad, Bangalore</code>).", body_style)
        ],
        [
            Paragraph("<b>Niche / Keywords</b>", body_style),
            Paragraph("Target business categories or keywords (e.g. <code>Restaurants, Plumbers, Gyms</code>).", body_style)
        ],
        [
            Paragraph("<b>Extra Info Filters</b>", body_style),
            Paragraph("Define quality criteria (e.g. <code>min rating 4.0, minimum 20 reviews</code>).", body_style)
        ],
        [
            Paragraph("<b>Target Emails</b>", body_style),
            Paragraph("Enter recipient emails to automatically send the finished Excel reports.", body_style)
        ],
        [
            Paragraph("<b>Leads per Query</b>", body_style),
            Paragraph("Enter target limit (e.g., <code>50</code>) to control how many leads are extracted.", body_style)
        ]
    ]

    steps_table = Table(steps_data, colWidths=[130, 374])
    steps_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(steps_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Running a Search Campaign", h2_style))
    story.append(Paragraph("1. Click <b>Start Scraping →</b>. The app will search Google Maps and visit business websites to extract contact info (phone numbers, addresses, emails).", bullet_style))
    story.append(Paragraph("2. Monitor the real-time progress, charts, and details inside the <b>What's happening?</b> log window on the right side of the screen.", bullet_style))
    story.append(Paragraph("3. Once scraping finishes, the leads are written to your local database and emailed as a spreadsheet report.", bullet_style))

    story.append(Paragraph("4. Viewing and Managing Reports", h1_style))
    story.append(Paragraph(
        "All compiled campaigns are saved under the **Reports** tab. "
        "Select any report and click <b>Open File</b> to view the Excel sheet instantly in Microsoft Excel, "
        "or click <b>Delete</b> to remove unwanted records.",
        body_style
    ))

    story.append(Paragraph("5. Troubleshooting Quick Check", h1_style))
    story.append(Paragraph("• <b>App closes immediately</b>: Make sure you extracted all files from the ZIP before running. Do not run it directly inside the ZIP view.", bullet_style))
    story.append(Paragraph("• <b>Connection Errors</b>: Verify your internet connection. A connection is required for online license verification and scraping.", bullet_style))
    story.append(Paragraph("• <b>No Emails Sent</b>: Check your <code>config.json</code> file. Ensure your sender SMTP details and receiver email lists are correctly written.", bullet_style))

    # Build Document
    doc.build(story, canvasmaker=NumberedCanvas)
    print("[+] PDF generated successfully!")


if __name__ == "__main__":
    create_user_guide()
