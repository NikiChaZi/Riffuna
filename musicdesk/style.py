STYLE = """
QWidget { color: #F4F1E8; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#root, QWidget#content, QStackedWidget { background: #101214; }
QFrame#sidebar, QFrame#queuePanel { background: #17191C; }
QFrame#sidebar { border-right: 1px solid #292D31; }
QFrame#queuePanel { border-left: 1px solid #292D31; }
QFrame#player { background: #191C1F; border-top: 1px solid #34383D; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 23px; font-weight: 700; letter-spacing: -1px; }
QLabel#eyebrow { color: #92999F; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#heroTitle { font-size: 32px; font-weight: 700; letter-spacing: -1px; }
QLabel#pageTitle { font-size: 26px; font-weight: 700; letter-spacing: -1px; }
QLabel#sectionTitle { font-size: 17px; font-weight: 650; }
QLabel#muted { color: #A3A8AD; }
QLabel#cardSubtitle { color: #989FA5; font-size: 12px; }
QLabel#tiny, QLabel#playerStatus { color: #92999F; font-size: 11px; }
QLabel#trackTitle { font-size: 14px; font-weight: 600; }
QLabel#badge { color: #E8C69B; background: #3C362C; padding: 0 5px; border-radius: 4px; font-size: 9px; font-weight: 600; }
QLabel#countBadge { color: #D8DBDD; background: #30363C; border-radius: 9px; padding: 2px 8px; font-size: 11px; }
QLabel#notice { background: #312B23; border: 1px solid #786149; border-radius: 8px; padding: 12px; color: #F2D3C4; }
QLabel#notice[error="true"] { background: #342624; border-color: #8A5149; color: #FFC0B6; }
QLabel#emptyTitle { color: #F4F1E8; font-size: 22px; font-weight: 600; }
QPushButton { border: 1px solid #3A453D; border-radius: 8px; padding: 9px 14px; background: #25292D; font-weight: 500; }
QPushButton:hover { background: #30353A; border-color: #626970; }
QPushButton:pressed { background: #393F45; }
QPushButton:focus { border: 1px solid #E3E6CD; }
QPushButton:disabled { color: #656C72; border-color: #292D31; background: #1E2226; }
QPushButton#primary { background: #FF875F; color: #151A19; border-color: #FF875F; font-weight: 650; }
QPushButton#primary:hover { background: #FFA080; border-color: #FFA080; }
QPushButton#primary:disabled { background: #704E3D; border-color: #704E3D; color: #B79987; }
QPushButton#listenAll { background: #E6D8B9; color: #1B241F; border-color: #E6D8B9; font-weight: 650; }
QPushButton#listenAll:hover { background: #F1E7CC; border-color: #F1E7CC; }
QPushButton#listenAll:disabled { background: #303438; border-color: #303438; color: #737A80; }
QPushButton#nav { text-align: left; border: 1px solid transparent; background: transparent; border-radius: 6px; padding: 11px 10px; color: #AEB4B9; }
QPushButton#nav:hover { background: #252A2F; color: #F4F1E8; }
QPushButton#nav:checked { color: #FFA080; background: #332B27; border-left: 2px solid #FF875F; }
QPushButton#nav:focus { border: 1px solid #747D85; }
QPushButton#iconButton { border: 1px solid transparent; background: transparent; padding: 0; }
QPushButton#iconButton:hover { background: #31373C; }
QPushButton#iconButton:checked { background: #44372C; }
QPushButton#iconButton:focus { border-color: #DEE0DB; }
QPushButton#playButton { border: none; background: #FF875F; border-radius: 22px; padding: 0; }
QPushButton#playButton:hover { background: #FFA080; }
QPushButton#playButton:disabled { background: #72503F; }
QPushButton#queryCard, QPushButton#libraryCard { text-align: left; background: #1C2024; border: 1px solid #33393E; padding: 0; border-radius: 10px; }
QPushButton#queryCard:hover, QPushButton#libraryCard:hover { border-color: #C39770; background: #292E33; }
QPushButton#outputButton { background: transparent; border-color: #41474D; font-size: 12px; padding: 7px 10px; }
QPushButton#outputButton:hover { background: #2D3339; }
QLineEdit { background: #1C2024; border: 1px solid #363D43; border-radius: 10px; padding: 10px 12px; font-size: 14px; selection-background-color: #86543D; }
QLineEdit:focus { border: 1px solid #FF875F; background: #24292E; }
QComboBox { background: #1C2024; border: 1px solid #363D43; border-radius: 7px; padding: 7px 30px 7px 12px; }
QComboBox:hover { border-color: #68727B; }
QComboBox:focus, QComboBox:on { border-color: #FF875F; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #20252A; border: 1px solid #59636B; outline: none; selection-background-color: #44372C; selection-color: #F4F1E8; padding: 4px; }
QFrame#sectionHeader { background: #1B1F23; border: 1px solid #343A40; border-radius: 10px; }
QFrame#queueNow { background: #252A2F; border: 1px solid #444C54; border-radius: 8px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: transparent; border: none; border-radius: 7px; }
QListWidget::item:selected { background: #3D322C; }
QListWidget::item:hover { background: #242A30; }
QFrame#trackRow { border: 1px solid transparent; border-radius: 7px; }
QFrame#trackRow[current="true"] { background: #2B2926; border-left: 2px solid #FF875F; }
QFrame#trackRow:hover { background: #242A30; }
QFrame#hero { background: #20252A; border: 1px solid #464E56; border-radius: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #414A52; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #737E88; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider { background: transparent; min-height: 18px; }
QSlider::groove:horizontal { height: 4px; background: #414950; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #FF875F; border-radius: 2px; }
QSlider::handle:horizontal { background: #F4F1E8; border: none; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
QSlider::handle:horizontal:hover { background: #FFAA8D; }
QSlider::sub-page:horizontal:disabled { background: #6D6F66; }
QToolTip { background: #292F35; color: #F4F1E8; border: 1px solid #68747D; padding: 6px; }
QMenu { background: #20252A; border: 1px solid #48545D; padding: 5px; }
QMenu::item { padding: 9px 20px; }
QMenu::item:selected { background: #343D45; }
"""

STYLE += """
QWidget#libraryPage { background: #101214; }
QPushButton#trackTile, QPushButton#playlistTile { background: #1C2024; border: 1px solid #30363C; border-radius: 10px; padding: 0; text-align: left; }
QPushButton#trackTile:hover, QPushButton#playlistTile:hover { background: #282E34; border-color: #BE9677; }
QPushButton#trackTile:pressed, QPushButton#playlistTile:pressed { background: #343B42; }
QPushButton#trackTile:focus, QPushButton#playlistTile:focus { border-color: #FFAA8D; }
QWidget#libraryEmpty { background: #1A1F23; border: 1px solid #333B42; border-radius: 10px; }
"""

STYLE += """
QWidget#sidebarContent { background: #17191C; }
QWidget#listTools QPushButton { padding: 7px 10px; }
QWidget#listTools QLabel#muted { font-size: 12px; }
"""

# New selectors remain scoped so forms and native popup controls keep their behavior.
STYLE += """
QLabel#pageTitle { font-size: 30px; font-weight: 750; letter-spacing: -1px; }
QLabel#sectionTitle { font-size: 20px; font-weight: 700; letter-spacing: -0.4px; }
QPushButton { border-radius: 10px; }
QPushButton#nav { border-radius: 10px; padding: 11px 12px; font-weight: 600; }
QPushButton#nav:checked { background: #302A27; border: 1px solid #514038; color: #FFA080; }
QPushButton#trackTile, QPushButton#playlistTile { background: #191D21; border: 1px solid transparent; border-radius: 12px; }
QPushButton#trackTile:hover, QPushButton#playlistTile:hover { background: #22282D; border-color: #3A4148; }
QPushButton#trackTile:focus, QPushButton#playlistTile:focus { border: 1px solid #FFAA8D; }
QLabel#tileTitle { font-size: 15px; font-weight: 650; }
QLabel#tileSubtitle { font-size: 12px; color: #9FA6AC; }
QLabel#libraryKicker { font-size: 10px; font-weight: 650; letter-spacing: 1.8px; color: #B9A99E; }
QLabel#libraryTitle { font-size: 36px; font-weight: 750; letter-spacing: -1.2px; }
QLabel#libraryIntro { font-size: 13px; color: #A3A8AD; }
QPushButton#sectionAction { border: 1px solid transparent; background: transparent; color: #CBC3B8; padding: 7px 4px; font-size: 12px; }
QPushButton#sectionAction:hover { color: #FFA080; background: #23272B; }
QPushButton#listeningHero { background: #262624; border: 1px solid #3D3D36; border-radius: 16px; padding: 0; text-align: left; }
QPushButton#listeningHero:hover { background: #30302B; border-color: #756253; }
QLabel#heroRecording { font-size: 30px; font-weight: 700; letter-spacing: -0.5px; }
QLabel#heroArtist { font-size: 14px; color: #C0BDB1; }
QLabel#heroAction { font-size: 12px; color: #FFAB8D; font-weight: 600; }
QWidget#libraryEmpty { background: #191D21; border: 1px solid #333940; border-radius: 16px; }
QLabel#emptyMark { color: #FF875F; }
QFrame#sectionHeader { background: transparent; border: none; border-bottom: 1px solid #30363B; border-radius: 0; }
QFrame#trackRow { border: 1px solid transparent; border-radius: 10px; }
QFrame#trackRow[current="true"] { background: #302B27; border: 1px solid #5B4033; border-left: 3px solid #FF875F; }
QFrame#trackRow[selected="true"] { background: #38312C; border: 1px solid #8C6049; }
QFrame#trackRow:hover { background: #252B30; }
QLabel#rowTitle { font-size: 14px; font-weight: 600; }
QLabel#rowDuration { color: #9CA4AB; font-size: 12px; }
QWidget#listTools QWidget#batchActions { background: #2D2825; border: 1px solid #654B3E; border-radius: 10px; }
QLabel#selectionCount { color: #FFD1BC; font-size: 12px; font-weight: 650; }
QWidget#listTools QPushButton#batchAction { background: transparent; border-color: transparent; padding: 6px 8px; font-size: 12px; }
QWidget#listTools QPushButton#batchAction:hover { background: #4A3930; border-color: #82624F; }
QWidget#listTools QLineEdit { font-size: 13px; padding: 8px 10px; border-radius: 9px; }
QWidget#listTools QComboBox { font-size: 12px; padding: 8px 28px 8px 10px; border-radius: 9px; }
QListWidget::item:selected { background: #38312C; }
QListWidget::item:selected:!active { background: #302D2A; }
QListWidget::item:focus { border: 1px solid #8C6049; }
"""

STYLE += """
QPushButton#rowPlay { background: rgba(16, 18, 20, 205); border: 1px solid #5C6367; border-radius: 16px; padding: 0; }
QPushButton#rowPlay:hover { background: #524139; border-color: #FFAA8D; }
QPushButton#rowPlay:focus { border: 1px solid #FF875F; }
QLabel#rowDuration { font-family: 'Consolas'; }
"""
