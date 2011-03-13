"""
Listing of the currently established connections tor has made.
"""

import time
import curses
import threading

from interface.connections import entries, connEntry
from util import connections, enum, panel, uiTools

DEFAULT_CONFIG = {"features.connection.listingType": 0,
                  "features.connection.refreshRate": 10}

# height of the detail panel content, not counting top and bottom border
DETAILS_HEIGHT = 7

# listing types
Listing = enum.Enum(("IP_ADDRESS", "IP Address"), "HOSTNAME", "FINGERPRINT", "NICKNAME")

DEFAULT_SORT_ORDER = (entries.SortAttr.CATEGORY, entries.SortAttr.LISTING, entries.SortAttr.UPTIME)

class ConnectionPanel(panel.Panel, threading.Thread):
  """
  Listing of connections tor is making, with information correlated against
  the current consensus and other data sources.
  """
  
  def __init__(self, stdscr, config=None):
    panel.Panel.__init__(self, stdscr, "connections", 0)
    threading.Thread.__init__(self)
    self.setDaemon(True)
    
    self._sortOrdering = DEFAULT_SORT_ORDER
    self._config = dict(DEFAULT_CONFIG)
    
    if config:
      config.update(self._config, {
        "features.connection.listingType": (0, len(Listing.values()) - 1),
        "features.connection.refreshRate": 1})
      
      sortFields = entries.SortAttr.values()
      customOrdering = config.getIntCSV("features.connection.order", None, 3, 0, len(sortFields))
      
      if customOrdering:
        self._sortOrdering = [sortFields[i] for i in customOrdering]
    
    self._listingType = Listing.values()[self._config["features.connection.listingType"]]
    self._scroller = uiTools.Scroller(True)
    self._title = "Connections:" # title line of the panel
    self._connections = []      # last fetched connections
    self._connectionLines = []  # individual lines in the connection listing
    self._showDetails = False   # presents the details panel if true
    
    self._lastUpdate = -1       # time the content was last revised
    self._isPaused = True       # prevents updates if true
    self._pauseTime = None      # time when the panel was paused
    self._halt = False          # terminates thread if true
    self._cond = threading.Condition()  # used for pausing the thread
    self.valsLock = threading.RLock()
    
    # Last sampling received from the ConnectionResolver, used to detect when
    # it changes.
    self._lastResourceFetch = -1
    
    self._update() # populates initial entries
    
    # TODO: should listen for tor shutdown
    # TODO: hasn't yet had its pausing functionality tested (for instance, the
    # key handler still accepts events when paused)
  
  def setPaused(self, isPause):
    """
    If true, prevents the panel from updating.
    """
    
    if not self._isPaused == isPause:
      self._isPaused = isPause
      
      if isPause: self._pauseTime = time.time()
      else: self._pauseTime = None
      
      # redraws so the display reflects any changes between the last update
      # and being paused
      self.redraw(True)
  
  def setSortOrder(self, ordering = None):
    """
    Sets the connection attributes we're sorting by and resorts the contents.
    
    Arguments:
      ordering - new ordering, if undefined then this resorts with the last
                 set ordering
    """
    
    self.valsLock.acquire()
    if ordering: self._sortOrdering = ordering
    self._connections.sort(key=lambda i: (i.getSortValues(self._sortOrdering, self._listingType)))
    
    self._connectionLines = []
    for entry in self._connections:
      self._connectionLines += entry.getLines()
    self.valsLock.release()
  
  def setListingType(self, listingType):
    """
    Sets the priority information presented by the panel.
    
    Arguments:
      listingType - Listing instance for the primary information to be shown
    """
    
    self.valsLock.acquire()
    self._listingType = listingType
    
    # if we're sorting by the listing then we need to resort
    if entries.SortAttr.LISTING in self._sortOrdering:
      self.setSortOrder()
    
    self.valsLock.release()
  
  def handleKey(self, key):
    self.valsLock.acquire()
    
    if uiTools.isScrollKey(key):
      pageHeight = self.getPreferredSize()[0] - 1
      if self._showDetails: pageHeight -= (DETAILS_HEIGHT + 1)
      isChanged = self._scroller.handleKey(key, self._connectionLines, pageHeight)
      if isChanged: self.redraw(True)
    elif uiTools.isSelectionKey(key):
      self._showDetails = not self._showDetails
      self.redraw(True)
    
    self.valsLock.release()
  
  def run(self):
    """
    Keeps connections listing updated, checking for new entries at a set rate.
    """
    
    lastDraw = time.time() - 1
    while not self._halt:
      currentTime = time.time()
      
      if self._isPaused or currentTime - lastDraw < self._config["features.connection.refreshRate"]:
        self._cond.acquire()
        if not self._halt: self._cond.wait(0.2)
        self._cond.release()
      else:
        # updates content if their's new results, otherwise just redraws
        self._update()
        self.redraw(True)
        lastDraw += self._config["features.connection.refreshRate"]
  
  def draw(self, width, height):
    self.valsLock.acquire()
    
    # extra line when showing the detail panel is for the bottom border
    detailPanelOffset = DETAILS_HEIGHT + 1 if self._showDetails else 0
    isScrollbarVisible = len(self._connectionLines) > height - detailPanelOffset - 1
    
    scrollLoc = self._scroller.getScrollLoc(self._connectionLines, height - detailPanelOffset - 1)
    cursorSelection = self._scroller.getCursorSelection(self._connectionLines)
    
    # draws the detail panel if currently displaying it
    if self._showDetails:
      # This is a solid border unless the scrollbar is visible, in which case a
      # 'T' pipe connects the border to the bar.
      uiTools.drawBox(self, 0, 0, width, DETAILS_HEIGHT + 2)
      if isScrollbarVisible: self.addch(DETAILS_HEIGHT + 1, 1, curses.ACS_TTEE)
      
      drawEntries = cursorSelection.getDetails(width)
      for i in range(min(len(drawEntries), DETAILS_HEIGHT)):
        drawEntries[i].render(self, 1 + i, 2)
    
    # title label with connection counts
    title = "Connection Details:" if self._showDetails else self._title
    self.addstr(0, 0, title, curses.A_STANDOUT)
    
    scrollOffset = 0
    if isScrollbarVisible:
      scrollOffset = 3
      self.addScrollBar(scrollLoc, scrollLoc + height - detailPanelOffset - 1, len(self._connectionLines), 1 + detailPanelOffset)
    
    currentTime = self._pauseTime if self._pauseTime else time.time()
    for lineNum in range(scrollLoc, len(self._connectionLines)):
      entryLine = self._connectionLines[lineNum]
      
      # hilighting if this is the selected line
      extraFormat = curses.A_STANDOUT if entryLine == cursorSelection else curses.A_NORMAL
      
      drawEntry = entryLine.getListingEntry(width - scrollOffset, currentTime, self._listingType)
      drawLine = lineNum + detailPanelOffset + 1 - scrollLoc
      drawEntry.render(self, drawLine, scrollOffset, extraFormat)
      if drawLine >= height: break
    
    self.valsLock.release()
  
  def stop(self):
    """
    Halts further resolutions and terminates the thread.
    """
    
    self._cond.acquire()
    self._halt = True
    self._cond.notifyAll()
    self._cond.release()
  
  def _update(self):
    """
    Fetches the newest resolved connections.
    """
    
    connResolver = connections.getResolver("tor")
    currentResolutionCount = connResolver.getResolutionCount()
    
    if self._lastResourceFetch != currentResolutionCount:
      self.valsLock.acquire()
      currentConnections = connResolver.getConnections()
      
      # Replacement listing of connections. We first populate it with any of
      # our old entries in currentConnections, then add new ConnectionEntries
      # for whatever remains.
      newConnections = []
      
      # preserves any ConnectionEntries they already exist
      for entry in self._connections:
        if isinstance(entry, connEntry.ConnectionEntry):
          connLine = entry.getLines()[0]
          connAttr = (connLine.local.getIpAddr(), connLine.local.getPort(),
                      connLine.foreign.getIpAddr(), connLine.foreign.getPort())
          
          if connAttr in currentConnections:
            newConnections.append(entry)
            currentConnections.remove(connAttr)
      
      # reset any display attributes for the entries we're keeping
      for entry in newConnections:
        entry.resetDisplay()
      
      # add new entries for any additions
      for lIp, lPort, fIp, fPort in currentConnections:
        newConnections.append(connEntry.ConnectionEntry(lIp, lPort, fIp, fPort))
      
      # Counts the relays in each of the categories. This also flushes the
      # type cache for all of the connections (in case its changed since last
      # fetched).
      
      categoryTypes = connEntry.Category.values()
      typeCounts = dict((type, 0) for type in categoryTypes)
      for entry in newConnections:
        if isinstance(entry, connEntry.ConnectionEntry):
          typeCounts[entry.getLines()[0].getType()] += 1
      
      # makes labels for all the categories with connections (ie,
      # "21 outbound", "1 control", etc)
      countLabels = []
      
      for category in categoryTypes:
        if typeCounts[category] > 0:
          countLabels.append("%i %s" % (typeCounts[category], category.lower()))
      
      if countLabels: self._title = "Connections (%s):" % ", ".join(countLabels)
      else: self._title = "Connections:"
      
      self._connections = newConnections
      
      self._connectionLines = []
      for entry in self._connections:
        self._connectionLines += entry.getLines()
      
      self.setSortOrder()
      self._lastResourceFetch = currentResolutionCount
      self.valsLock.release()

