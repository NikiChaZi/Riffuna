STYLE = """
QWidget { color: #F4F1E8; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#root, QWidget#content, QStackedWidget { background: #111615; }
QFrame#sidebar, QFrame#queuePanel { background: #191F1D; }
QFrame#sidebar { border-right: 1px solid #2C3430; }
QFrame#queuePanel { border-left: 1px solid #2C3430; }
QFrame#player { background: #1D2521; border-top: 1px solid #3B463E; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 23px; font-weight: 700; letter-spacing: -1px; }
QLabel#eyebrow { color: #9DAA9D; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#heroTitle { font-size: 32px; font-weight: 700; letter-spacing: -1px; }
QLabel#pageTitle { font-size: 26px; font-weight: 700; letter-spacing: -1px; }
QLabel#sectionTitle { font-size: 17px; font-weight: 650; }
QLabel#muted { color: #AFBAAF; }
QLabel#cardSubtitle { color: #A9B5AA; font-size: 12px; }
QLabel#tiny, QLabel#playerStatus { color: #9DAA9D; font-size: 11px; }
QLabel#trackTitle { font-size: 14px; font-weight: 600; }
QLabel#badge { color: #E8C69B; background: #3C362C; padding: 0 5px; border-radius: 4px; font-size: 9px; font-weight: 600; }
QLabel#countBadge { color: #D3DDCD; background: #303B32; border-radius: 9px; padding: 2px 8px; font-size: 11px; }
QLabel#notice { background: #312B23; border: 1px solid #786149; border-radius: 8px; padding: 12px; color: #F2D3C4; }
QLabel#notice[error="true"] { background: #342624; border-color: #8A5149; color: #FFC0B6; }
QLabel#emptyTitle { color: #F4F1E8; font-size: 22px; font-weight: 600; }
QPushButton { border: 1px solid #3A453D; border-radius: 8px; padding: 9px 14px; background: #29332C; font-weight: 500; }
QPushButton:hover { background: #354238; border-color: #6D7C67; }
QPushButton:pressed { background: #414D3F; }
QPushButton:focus { border: 1px solid #E3E6CD; }
QPushButton:disabled { color: #758071; border-color: #2B342C; background: #222A24; }
QPushButton#primary { background: #FF875F; color: #151A19; border-color: #FF875F; font-weight: 650; }
QPushButton#primary:hover { background: #FFA080; border-color: #FFA080; }
QPushButton#primary:disabled { background: #704E3D; border-color: #704E3D; color: #B79987; }
QPushButton#listenAll { background: #E6D8B9; color: #1B241F; border-color: #E6D8B9; font-weight: 650; }
QPushButton#listenAll:hover { background: #F1E7CC; border-color: #F1E7CC; }
QPushButton#listenAll:disabled { background: #353C31; border-color: #353C31; color: #7E8977; }
QPushButton#nav { text-align: left; border: 1px solid transparent; background: transparent; border-radius: 6px; padding: 11px 10px; color: #B8C2B6; }
QPushButton#nav:hover { background: #29342C; color: #F4F1E8; }
QPushButton#nav:checked { color: #FFA080; background: #35342B; border-left: 2px solid #FF875F; }
QPushButton#nav:focus { border: 1px solid #89977F; }
QPushButton#iconButton { border: 1px solid transparent; background: transparent; padding: 0; }
QPushButton#iconButton:hover { background: #394538; }
QPushButton#iconButton:checked { background: #44372C; }
QPushButton#iconButton:focus { border-color: #D2D8C9; }
QPushButton#playButton { border: none; background: #FF875F; border-radius: 22px; padding: 0; }
QPushButton#playButton:hover { background: #FFA080; }
QPushButton#playButton:disabled { background: #72503F; }
QPushButton#queryCard, QPushButton#libraryCard { text-align: left; background: #202923; border: 1px solid #364438; padding: 0; border-radius: 10px; }
QPushButton#queryCard:hover, QPushButton#libraryCard:hover { border-color: #C39770; background: #29372B; }
QPushButton#outputButton { background: transparent; border-color: #46513F; font-size: 12px; padding: 7px 10px; }
QPushButton#outputButton:hover { background: #34402F; }
QLineEdit { background: #202923; border: 1px solid #40503F; border-radius: 10px; padding: 10px 12px; font-size: 14px; selection-background-color: #86543D; }
QLineEdit:focus { border: 1px solid #FF875F; background: #252F28; }
QComboBox { background: #202923; border: 1px solid #40503F; border-radius: 7px; padding: 7px 30px 7px 12px; }
QComboBox:hover { border-color: #73856A; }
QComboBox:focus, QComboBox:on { border-color: #FF875F; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
QComboBox QAbstractItemView { background: #252E26; border: 1px solid #68785D; outline: none; selection-background-color: #44372C; selection-color: #F4F1E8; padding: 4px; }
QFrame#sectionHeader { background: #202A23; border: 1px solid #334331; border-radius: 10px; }
QFrame#queueNow { background: #29342A; border: 1px solid #42543E; border-radius: 8px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { background: transparent; border: none; border-radius: 7px; }
QListWidget::item:selected { background: #2D3B2D; }
QListWidget::item:hover { background: #253326; }
QFrame#trackRow { border: 1px solid transparent; border-radius: 7px; }
QFrame#trackRow[current="true"] { background: #303A2B; border-left: 2px solid #FF875F; }
QFrame#trackRow:hover { background: #29392A; }
QFrame#hero { background: #253429; border: 1px solid #4B6248; border-radius: 12px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #4B5B44; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #7C906C; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSlider { background: transparent; min-height: 18px; }
QSlider::groove:horizontal { height: 4px; background: #4C5B43; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #FF875F; border-radius: 2px; }
QSlider::handle:horizontal { background: #F4F1E8; border: none; width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }
QSlider::handle:horizontal:hover { background: #FFAA8D; }
QSlider::sub-page:horizontal:disabled { background: #7D8063; }
QToolTip { background: #354330; color: #F4F1E8; border: 1px solid #81916F; padding: 6px; }
QMenu { background: #253225; border: 1px solid #546B49; padding: 5px; }
QMenu::item { padding: 9px 20px; }
QMenu::item:selected { background: #3E5135; }
"""

STYLE += """
QWidget#libraryPage { background: #111615; }
QPushButton#trackTile, QPushButton#playlistTile { background: #202923; border: 1px solid #354136; border-radius: 10px; padding: 0; text-align: left; }
QPushButton#trackTile:hover, QPushButton#playlistTile:hover { background: #2A362D; border-color: #BE9677; }
QPushButton#trackTile:pressed, QPushButton#playlistTile:pressed { background: #364333; }
QPushButton#trackTile:focus, QPushButton#playlistTile:focus { border-color: #FFAA8D; }
QWidget#libraryEmpty { background: #1D2720; border: 1px solid #354437; border-radius: 10px; }
"""
