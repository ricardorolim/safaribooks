class TableOfContents:
    navmap: str
    children: int
    depth: int

    def __init__(self, navmap, children, depth):
        self.navmap = navmap
        self.children = children
        self.depth = depth
