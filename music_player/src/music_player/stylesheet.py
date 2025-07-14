grey = "rgba(34,34,34,255)"

stylesheet = f"""
#MainWindow {{ background-color: black; }}
#AlbumButton {{ padding: 0px; }}
#OpacityButton:checked {{ background: transparent; }}
#OpacityButton:hover {{ background: transparent; }}
#InteractiveDialogue {{ border-radius: 5px; border: 1px solid white; }}
QScrollArea {{ padding: 0px; margin: 0px; border: none; }}
#StackGraphicsView {{border: none; margin: 0px; background: {grey}}}
QTabWidget > QTabBar::tab {{
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: {grey};
    margin-left: 2px;
    margin-right: 2px;
}}
QTabWidget > QTabBar {{ padding: 0px; background: transparent; }}
#MusicLibrary {{ margin: 0px; border: none; }}
#ElidedTextLabel {{ padding: 0px; margin: 0px; }}
#LibraryTableHeader {{ background: transparent; }}
#LibraryTableHeader::section {{ background: grey; }}
#LibraryTableView {{ background-color: {grey}; border: none; }}
#LibraryTableView::item {{ background: transparent; }}
#SortMenu::item {{ padding: 5px; spacing: 0px; }}
#SortButton {{ padding: 5px; }}
#SortButton::menu-indicator {{ image: none; }}
#MediaToolbar {{ background: transparent; }}
#MediaToolbar QWidget {{ background: transparent;  border: 1px solid red; }}
#CloseButton {{ border: none; }}
QDialog QPushButton {{ border-radius: 5px; }}
#NewCollectionButton {{ border-radius: 5px; background: grey}}
#NewCollectionButton::menu-indicator {{ image: none; }}
#PlaylistTreeWidget {{ background-color: {grey}; border-radius: 5px; }}
#PlaylistTreeWidget QWidget {{ margin: 0px; border: none; }}
#PlaylistTreeHeader {{ background: transparent; }}
#PlaylistTreeWidget QTreeView {{ background: transparent; }}
#WarningLabel {{ border-radius: 5px; padding: 5px; background: red;}}
"""
