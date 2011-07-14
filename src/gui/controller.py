import gobject
import gtk

import thread
import time

from util import log, torTools
from connections import connPanel
from gui import logPanel, generalPanel
from gui.graphing import bandwidthStats

gobject.threads_init()

class GuiController:
  def __init__(self):
    filename = 'src/gui/arm.xml'

    self.builder = gtk.Builder()
    self.builder.add_from_file(filename)
    self.builder.connect_signals(self)

    self.logPanel = logPanel.LogPanel(self.builder)
    self.logPanel.pack_widgets()

    self.bwStats = bandwidthStats.BandwidthStats(self.builder)
    self.bwStats.pack_widgets()

    self.connPanel = connPanel.ConnectionPanel(self.builder)
    self.connPanel.pack_widgets()
    self.connPanel.start()

    self.generalPanel = generalPanel.GeneralPanel(self.builder)
    self.generalPanel.pack_widgets()

  def run(self):
    window = self.builder.get_object('window_main')

    window.show_all()
    gtk.main()

  def on_action_about_activate(self, widget, data=None):
    dialog = self.builder.get_object('aboutdialog')
    dialog.run()

  def on_aboutdialog_response(self, widget, responseid, data=None):
    dialog = self.builder.get_object('aboutdialog')
    dialog.hide()

  def on_action_quit_activate(self, widget, data=None):
    gtk.main_quit()

  def on_window_main_delete_event(self, widget, data=None):
    gtk.main_quit()

def startGui():
  controller = GuiController()
  controller.run()

