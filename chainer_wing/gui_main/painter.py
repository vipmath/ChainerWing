import json
import logging
import os

import chainer
import numpy
from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from chainer_wing import util
from chainer_wing.gui_main.mainwindow import Ui_MainWindow
from chainer_wing.subwindows.data_config import DataDialog
from chainer_wing.subwindows.image_data_config import ImageDataDialog
from chainer_wing.subwindows.settings import SettingsDialog
from chainer_wing.subwindows.train_config import TrainDialog
from chainer_wing.subwindows.train_config import TrainParamServer
from chainer_wing.subwindows.prediction_widget import PredictionWindow

logger = logging.getLogger('ChainerWing')

PINSIZE = 8
TEXTYOFFSET = 0


class Painter2D(QtWidgets.QWidget):
    PINCOLORS = {str: QtGui.QColor(255, 190, 0),
                 int: QtGui.QColor(0, 115, 130),
                 float: QtGui.QColor(0, 200, 0),
                 object: QtGui.QColor(190, 190, 190),
                 bool: QtGui.QColor(190, 0, 0),
                 chainer.Variable: QtGui.QColor(100, 0, 100),
                 numpy.ndarray: QtGui.QColor(100, 0, 200), }
    nodes = []
    scale = 1.
    globalOffset = QtCore.QPoint(0, 0)
    drag = False
    inputPinPositions = []
    clickedPin = None
    clickedNode = None
    nodePoints = []
    downOverNode = False

    def __init__(self, parent=None):
        super(Painter2D, self).__init__(parent)
        self.setMouseTracking(True)
        self.timer = QtCore.QTimer()
        self.timer.start(500)
        self.setFocusPolicy(Qt.ClickFocus)
        self.graph = None
        self.looseConnection = None
        self.reportWidget = None
        self.pinPositions = {}
        self.drawItems = []
        self.drawItemsOfNode = {}
        self.watchingItems = set()
        self.rightClickedNode = None
        self.mouseDownPos = None
        self.relayTo = None
        self.selectFrame = None
        self.selectFrame_End = None
        self.groupSelection = []
        self.copied_node = None
        self.graph_stack = []  # For undo/redo
        self.max_graph_stack = 20
        self.reset()

    def reset(self):
        self.nodes = []
        self.graph = None
        self.looseConnection = None
        self.reportWidget = None
        self.pinPositions = {}
        self.drawItems = []
        self.drawItemsOfNode = {}
        self.watchingItems = set()
        self.rightClickedNode = None
        self.mouseDownPos = None
        self.relayTo = None
        self.selectFrame = None
        self.selectFrame_End = None
        self.groupSelection = []
        self.copied_node = None

    def update_graph_stack(self):
        """
        This method should be called After graph manipulated.
        """
        if self.graph is None:
            return
        self.graph_stack.append(self.graph.to_dict())  # For undo/redo
        if len(self.graph_stack) > self.max_graph_stack:
            self.graph_stack.pop()

    def undo_graph(self):
        """
        Undo graph manipulation by graph_stack.
        """
        if not self.graph_stack:
            return
        self.clear_all_nodes()
        self.graph_stack.pop(-1)
        self.graph.load_from_dict(self.graph_stack[-1])

    def relayInputEventsTo(self, drawItem):
        self.relayTo = drawItem

    def stopInputRelayingTo(self, drawItem):
        if self.relayTo == drawItem:
            self.relayTo = None

    def registerWatchingItem(self, item):
        self.watchingItems.add(item)

    def removeWatchingItem(self, item):
        self.watchingItems.remove(item)

    def registerGraph(self, graph):
        self.graph = graph

    def keyPressEvent(self, event):
        super(Painter2D, self).keyPressEvent(event)
        if self.relayTo:
            self.relayTo.keyPressEvent(event)

    def keyReleaseEvent(self, event):
        super(Painter2D, self).keyReleaseEvent(event)

    def wheelEvent(self, event):
        up = event.angleDelta().y() > 0
        if up:
            x = 1.1
        else:
            x = .9
        self.scale *= x
        self.repaint()
        self.update()

    def mousePressEvent(self, event):
        self.mouseDownPos = event.pos()
        if event.button() == Qt.RightButton:
            self.rightClickedNode = None
            for nodePoints in self.nodePoints:
                x1 = nodePoints[0].x()
                x2 = nodePoints[1].x()  # + x1
                y1 = nodePoints[0].y()
                y2 = nodePoints[1].y()  # + y1
                xx = event.pos()
                yy = xx.y()
                xx = xx.x()
                if x1 < xx < x2 and y1 < yy < y2:
                    self.rightClickedNode = nodePoints[-1]
                    break
            if not self.rightClickedNode:
                self.drag = event.pos()

        if event.button() == Qt.LeftButton:
            for drawItem in self.drawItems:
                if issubclass(type(drawItem), Selector) or issubclass(
                        type(drawItem), LineEdit):
                    if drawItem.collide(event.pos()):
                        break

            for point, i in self.inputPinPositions:
                if abs(event.pos().x() - point.x()) < PINSIZE * self.scale and abs(
                            event.pos().y() - point.y()) < PINSIZE * self.scale:
                    self.clickedPin = i
                    if i[-8:] != 'in_array':
                        self.clickedPin = None
                        return
                    self.graph.removeConnection(i, from_self=False)
                    self.update()
                    self.update_graph_stack()
                    return

            for point, i in self.outputPinPositions:
                if abs(event.pos().x() - point.x()) < PINSIZE * self.scale and abs(
                            event.pos().y() - point.y()) < PINSIZE * self.scale:
                    self.clickedPin = i
                    self.graph.removeConnection(i, from_self=True)
                    self.update()
                    self.update_graph_stack()
                    return

            for nodePoints in self.nodePoints:
                x1 = nodePoints[0].x()
                x2 = nodePoints[1].x()  # + x1
                y1 = nodePoints[0].y()
                y2 = nodePoints[1].y()  # + y1
                xx = event.pos()
                yy = xx.y()
                xx = xx.x()
                if x1 < xx < x2 and y1 < yy < y2:
                    self.clickedNode = nodePoints[-1]
                    self.update()
                    self.update_graph_stack()
                    self.downOverNode = event.pos()
                    return
            self.groupSelection = []
            self.selectFrame = event.pos() + (event.pos() - self.center) * (
                1 - self.scale) * 1 / self.scale
            self._selectFrame = event.pos()

    def getOutputPinAt(self, pos):
        for point, pin in self.outputPinPositions:
            if abs(pos.x() - point.x()) < 16 * self.scale and abs(
                            pos.y() - point.y()) < 16 * self.scale:
                return pin

    def getInputPinAt(self, pos):
        for point, pin in self.inputPinPositions:
            if abs(pos.x() - point.x()) < 16 * self.scale and abs(
                            pos.y() - point.y()) < 16 * self.scale:
                if pin[-8:] != 'in_array':
                    return None
                return pin

    def mouseReleaseEvent(self, event):
        super(Painter2D, self).mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self.looseConnection and self.clickedPin:
            valid = True
            if ':I' in self.clickedPin:
                input_nodeID, _, input_name = self.clickedPin.partition(':I')
                try:
                    output_nodeID, _, output_name = self.getOutputPinAt(
                        event.pos()).partition(':O')
                except AttributeError:
                    valid = False
            else:
                output_nodeID, _, output_name = self.clickedPin.partition(':O')
                try:
                    input_nodeID, _, input_name = self.getInputPinAt(
                        event.pos()).partition(':I')
                except AttributeError:
                    valid = False
            if valid:
                try:
                    self.graph.connect(output_nodeID, output_name, input_nodeID,
                                       input_name)
                    # self.update_graph_stack()
                except TypeError:
                    util.disp_error('Cannot connect pins of different type')
            self.looseConnection = False
            self.clickedPin = None
        self.drag = False
        self.downOverNode = False

        if self.selectFrame and self.selectFrame_End:
            x1, x2 = self._selectFrame.x(), self._selectFrame_End.x()
            if x1 > x2:
                x2, x1 = x1, x2
            y1, y2 = self._selectFrame.y(), self._selectFrame_End.y()
            if y1 > y2:
                y2, y1 = y1, y2
            self.groupSelection = self.massNodeCollide(x1, y1,
                                                       x2, y2)
        self.selectFrame = None
        self.selectFrame_End = None
        self.repaint()
        self.update()

    def massNodeCollide(self, x, y, xx, yy):
        nodes = []
        for nodePoints in self.nodePoints:
            x1 = nodePoints[0].x()
            x2 = nodePoints[1].x()  # + x1
            y1 = nodePoints[0].y()
            y2 = nodePoints[1].y()  # + y1
            if x < x1 < xx and y < y1 < yy and x < x2 < xx and y < y2 < yy:
                nodes.append(nodePoints[-1])
        return nodes

    def mouseMoveEvent(self, event):
        for drawItem in self.watchingItems:
            drawItem.watch(event.pos())
        super(Painter2D, self).mouseMoveEvent(event)

        if self.drag:
            self.globalOffset += event.pos() - self.drag
            self.drag = event.pos()
            self.update()
            self.update_graph_stack()
        if self.downOverNode:
            if self.groupSelection:
                for node in self.groupSelection:
                    newPos = (event.pos() - self.downOverNode) / self.scale
                    oldPos = QtCore.QPoint(node.__pos__[0], node.__pos__[1])
                    newPos = oldPos + newPos
                    node.__pos__ = (newPos.x(), newPos.y())
                self.downOverNode = event.pos()
                self.update()
                self.update_graph_stack()
            else:
                node = self.clickedNode
                newPos = (event.pos() - self.downOverNode) / self.scale
                oldPos = QtCore.QPoint(node.__pos__[0], node.__pos__[1])
                newPos = oldPos + newPos
                node.__pos__ = (newPos.x(), newPos.y())
                self.downOverNode = event.pos()
                self.update()
                self.update_graph_stack()

        else:
            self.drawLooseConnection(event.pos())
            self.update()
            self.update_graph_stack()
        if self.selectFrame:
            self.selectFrame_End = event.pos() + (event.pos() - self.center) * (
                1 - self.scale) * 1 / self.scale
            self._selectFrame_End = event.pos()

    def getSelectedNode(self):
        return self.clickedNode

    def contextMenuEvent(self, event):
        node = self.rightClickedNode
        menu = QtWidgets.QMenu(self)
        if not node:
            paste_action = menu.addAction('Paste node')
            action = menu.exec_(self.mapToGlobal(event.pos()))
            if action == paste_action:
                self.paste_node(event.pos())
            return

        copy_action = menu.addAction('Copy node')
        rename_action = menu.addAction('Rename node')
        delete_action = menu.addAction('Delete node')

        action = menu.exec_(self.mapToGlobal(event.pos()))
        if action == delete_action:
            self.delete_node(node)
        elif action == rename_action:
            self.rename_node(node)
        elif action == copy_action:
            self.copy_node(node)
        return

    def delete_node(self, node):
        self.clear_node(node)
        self.repaint()
        self.update_graph_stack()
        # release clicked node for prevent double deleting.
        self.clickedNode = None

    def clear_node(self, node):
        self.graph.deleteNode(node)
        self.unregisterNode(node)
        node.clear()

    def clear_all_nodes(self, repaint=True):
        while self.nodes:
            node = self.nodes[0]
            self.clear_node(node)
        if repaint:
            self.repaint()

    def copy_node(self, node):
        self.copied_node = node
        self.update_graph_stack()

    def paste_node(self, pos=None):
        if self.copied_node is None:
            return
        if pos is None:
            pos = self.copied_node.__pos__
            pos = QtCore.QPoint(pos[0] - 5, pos[1] - 5)
        else:
            pos -= self.center
            pos /= self.scale
        self.graph.pasteNode(self.copied_node, pos)
        self.update_graph_stack()
        self.repaint()

    def correct_pos(self, pos):
        pos -= self.mapToGlobal(self.pos())  # get top left
        pos -= self.center
        pos /= self.scale
        return pos

    def get_all_name(self):
        return [node.get_name() for node in self.nodes]

    def rename_node(self, node):
        text, ok = QtWidgets.QInputDialog.getText(self, 'Rename node',
                                                  'Enter new name:')
        if ok and text and text not in self.get_all_name():
            node.name = text
            self.repaint()
            self.update_graph_stack()

    def paintEvent(self, event):
        self.inputPinPositions = []
        self.outputPinPositions = []
        self.nodePoints = []
        super(Painter2D, self).paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.HighQualityAntialiasing)
        self.drawGrid(painter)
        try:
            self.drawConnections(painter)
        except KeyError:
            pass

        painter.translate(self.width() / 2. + self.globalOffset.x(),
                          self.height() / 2. + self.globalOffset.y())
        self.center = QtCore.QPoint(self.width() / 2. + self.globalOffset.x(),
                                    self.height() / 2. + self.globalOffset.y())
        painter.scale(self.scale, self.scale)
        painter.setRenderHint(QtGui.QPainter.HighQualityAntialiasing)

        lastDraws = []
        halfPinSize = PINSIZE // 2

        for node in self.nodes:
            pen = QtGui.QPen()
            pen.setWidth(2)
            if node.runtime_error_happened:
                painter.setBrush(QtGui.QColor(125, 45, 45))
            elif hasattr(node, 'color'):
                painter.setBrush(node.color())
            else:
                painter.setBrush(QtGui.QColor(55, 55, 55))
            if self.clickedNode == node or node in self.groupSelection:
                painter.setBrush(QtGui.QColor(75, 75, 75))

            font = QtGui.QFont('Helvetica', 12)
            painter.setFont(font)
            path = QtGui.QPainterPath()
            x = node.__pos__[0]  # + self.globalOffset.x()
            y = node.__pos__[1]  # + self.globalOffset.y()
            w = node.__size__[0] * self.settings.value('NodeWidth')
            if len(node.__class__.__name__) > 10:
                w += len(node.__class__.__name__) * 4
            h = node.__size__[1] * (8 + PINSIZE) + 40

            path.addRoundedRect(x, y, w, h, 50, 5)
            self.nodePoints.append((QtCore.QPoint(x, y) * painter.transform(),
                                    QtCore.QPoint(x + w, y + h) * painter.transform(),
                                    node))
            painter.setPen(pen)

            painter.fillPath(path, QtGui.QColor(55, 55, 55))
            painter.drawPath(path)
            pen.setColor(QtGui.QColor(150, 150, 150))
            painter.setFont(
                QtGui.QFont('Helvetica', self.settings.value('NodeTitleFontSize')))
            painter.setPen(pen)
            painter.drawText(x, y + 3, w, h, Qt.AlignHCenter,
                             node.__class__.__name__)
            painter.drawText(x, y + 20, w, h, Qt.AlignHCenter,
                             node.get_name())
            painter.setBrush(QtGui.QColor(40, 40, 40))
            drawOffset = 33
            for i, drawItem in enumerate(self.drawItemsOfNode[node]['inp']):
                inputPin = drawItem.data
                try:
                    pen.setColor(Painter2D.PINCOLORS[inputPin.info.var_type[0]])
                except KeyError:
                    pen.setColor(QtGui.QColor(*inputPin.info.var_type[0].color))
                pen.setWidth(2)
                painter.setPen(pen)
                if inputPin.ID == self.clickedPin:
                    pen.setColor(Qt.red)
                    painter.setPen(pen)

                if inputPin.info.var_type[0] is chainer.Variable:
                    painter.drawEllipse(x - halfPinSize,
                                        y + drawOffset + PINSIZE, PINSIZE,
                                        PINSIZE)
                point = QtCore.QPoint(x, y + drawOffset + 4 + PINSIZE)
                point *= painter.transform()
                self.inputPinPositions.append((point, inputPin.ID))
                drawOffset += (8 + PINSIZE)
                drawItem.update(x, y + drawOffset + 8, w, h,
                                painter.transform())
                if self.graph.getConnectionOfInput(inputPin) is not None:
                    text = inputPin.name
                    drawItem.draw(painter, as_label=text)
                else:
                    item = drawItem.draw(painter)
                    if item:
                        lastDraws.append(item)

            for k, drawItem in enumerate(self.drawItemsOfNode[node]['out']):
                outputPin = drawItem.data
                try:
                    pen.setColor(Painter2D.PINCOLORS[outputPin.info.var_type[0]])
                except KeyError:
                    pen.setColor(QtGui.QColor(*outputPin.info.var_type[0].color))
                pen.setWidth(2)
                painter.setPen(pen)
                if outputPin.ID == self.clickedPin:
                    pen.setColor(Qt.red)
                    painter.setPen(pen)
                else:
                    painter.drawEllipse(x + w - halfPinSize,
                                        y + drawOffset + PINSIZE, PINSIZE,
                                        PINSIZE)
                    point = QtCore.QPoint(x + w - 4,
                                   y + drawOffset + 4 + PINSIZE) * painter.transform()
                drawOffset += (8 + PINSIZE)
                self.outputPinPositions.append((point, outputPin.ID))
                drawItem.update(x, y + drawOffset + 8, w, h,
                                painter.transform())
                drawItem.draw(painter)

        self.pinPositions = {value[1]: value[0] for value in
                             self.inputPinPositions + self.outputPinPositions}
        for item in lastDraws:
            item.draw(painter, last=True)

        self.draw_selection(painter)

    def draw_selection(self, painter):
        if self.selectFrame and self.selectFrame_End:
            painter.setBrush(QtGui.QColor(255, 255, 255, 25))
            painter.setPen(Qt.white)
            x = self.selectFrame.x()
            y = self.selectFrame.y()
            xx = self.selectFrame_End.x() - x
            yy = self.selectFrame_End.y() - y
            painter.translate(-self.width() / 2. - self.globalOffset.x(),
                              -self.height() / 2. - self.globalOffset.y())
            painter.drawRect(x, y, xx, yy)
            painter.translate(self.width() / 2. + self.globalOffset.x(),
                              self.height() / 2. + self.globalOffset.y())

    def drawConnections(self, painter):
        if not self.graph:
            print('No graph connected yet.')
            return
        if not self.pinPositions:
            return

        if self.looseConnection and self.clickedPin:
            start = self.pinPositions[self.clickedPin]
            if ':I' in self.clickedPin:
                start, end = self.looseConnection, start
            else:
                end = self.looseConnection
            self.drawBezier(start, end, Qt.white, painter)

        for output_node, connList in self.graph.connections.items():
            for info in connList:
                outputID = output_node.getOutputID(info.output_name)
                inputID = info.input_node.getInputID(info.input_name)
                var_type = output_node.getOutputInfo(info.output_name).var_type
                start = self.pinPositions[outputID]
                end = self.pinPositions[inputID]
                try:
                    color = Painter2D.PINCOLORS[var_type[0]]
                except KeyError:
                    color = QtGui.QColor(*var_type[0].color)
                rotate = None
                self.drawBezier(start, end, color, painter, rotate)

    def drawLooseConnection(self, position):
        self.looseConnection = position

    def drawBezier(self, start, end, color, painter, rotate=None):
        pen = QtGui.QPen()
        pen.setColor(color)
        pen.setWidth(self.settings.value('ConnectionLineWidth') * self.scale)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(start)
        diffx = abs((start.x() - end.x()) / 2.)
        if diffx < 100 * self.scale:
            diffx = 100 * self.scale
        if rotate == 'input':
            p21 = start.x() + diffx
            p22 = start.y()
            p31 = end.x()
            p32 = end.y() - 100 * self.scale
        elif rotate == 'output':
            p21 = start.x()
            p22 = start.y() + 100 * self.scale
            p31 = end.x() - diffx
            p32 = end.y()
        elif rotate == 'both':
            p21 = start.x()
            p22 = start.y() + 100 * self.scale
            p31 = end.x()
            p32 = end.y() - 100 * self.scale
        else:
            p21 = start.x() + diffx
            p22 = start.y()
            p31 = end.x() - diffx
            p32 = end.y()
        path.cubicTo(p21, p22, p31, p32, end.x(), end.y())
        painter.drawPath(path)

    def registerNode(self, node, silent=False):
        if not silent:
            self.parent().parent().parent().parent().statusBar.showMessage(
                'Spawned node of class \'{}\'.'.format(type(node).__name__),
                2000)
        node.__size__ = (1, len(node.inputs) + len(node.outputs))
        self.nodes.append(node)
        self.drawItemsOfNode[node] = {'inp': [], 'out': []}
        for out in node.outputPins.values():
            if out.info.select:
                s = Selector(node, out, self)
            else:
                s = OutputLabel(node, out, self)
            self.drawItems.append(s)
            self.drawItemsOfNode[node]['out'].append(s)
        for inp in node.inputPins.values():
            if inp.info.select:
                s = Selector(node, inp, self)
            else:
                s = LineEdit(node, inp, self)
            self.drawItems.append(s)
            self.drawItemsOfNode[node]['inp'].append(s)

    def unregisterNode(self, node):
        self.nodes.remove(node)
        del self.drawItemsOfNode[node]

    def drawGrid(self, painter):
        color = 105
        spacing = 100 * self.scale

        # More zoom up, use darker grid.
        while spacing < 25:
            spacing *= 9
            color = 70 + (color - 70) / 2.5
        if color < 0:
            return

        pen = QtGui.QPen()
        pen.setColor(QtGui.QColor(color, color, color))
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        verticalN = int(self.width() / spacing / 2) + 1
        horizontalN = int(self.height() / spacing / 2) + 1
        for i in range(verticalN):
            painter.drawLine(self.width() / 2 + i * spacing, 0,
                             self.width() / 2 + i * spacing, self.height())
            painter.drawLine(QtCore.QPoint(self.width() / 2 - i * spacing, 0),
                             QtCore.QPoint(self.width() / 2 - i * spacing,
                                           self.height()))

        for i in range(horizontalN):
            painter.drawLine(0, self.height() / 2 + i * spacing, self.width(),
                             self.height() / 2 + i * spacing)
            painter.drawLine(0, self.height() / 2 - i * spacing, self.width(),
                             self.height() / 2 - i * spacing)

    def set_settings(self, settings):
        self.settings = settings


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, parent=None, painter=None):
        super(MainWindow, self).__init__(parent)

        self.iconRoot = os.path.join(os.path.dirname(__file__), '../resources')
        self.settings = QtCore.QSettings('ChainerWing', 'ChainerWing')

        self.select_data_button = QtWidgets.QPushButton('')
        self.select_data_button.clicked.connect(self.open_data_config)
        self.select_data_button.setToolTip('Select training data')

        self.setupUi(self)

        self.setWindowIcon(
            QtGui.QIcon(os.path.join(self.iconRoot, 'appIcon.png')))

        try:
            self.resize(self.settings.value("size", (900, 700)))
            self.move(self.settings.value("pos", QtCore.QPoint(50, 50)))
            init_graph = self.settings.value("graph_file", '')
        except TypeError:
            pass
        self.setWindowTitle('ChainerWind')

        self.initActions()
        self.initMenus()

        painter.reportWidget = self.BottomWidget
        painter.set_settings(self.settings)

        painter.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(painter.backgroundRole(), QtGui.QColor(70, 70, 70))
        painter.setPalette(p)
        l = QtWidgets.QGridLayout()
        l.addWidget(painter)
        self.DrawArea.setLayout(l)
        self.drawer = painter

        # to reflect initial configuration
        SettingsDialog(self, settings=self.settings).close()
        TrainDialog(self, settings=self.settings).close()
        ImageDataDialog(self, settings=self.settings).close()
        DataDialog(self, settings=self.settings).close()
        self.update_data_label()
        self.setupNodeLib()

        # Open Last Opened JSON if enable
        TrainParamServer()['ProjectName'] = 'New Project'
        try:
            if init_graph:
                self.load_graph(init_graph)
        except FileNotFoundError:
            pass

    def setArgs(self, args):
        if args.test:
            logger.info('Performing test.')
            self.load_graph(override=args.test[0])
            self.compile_and_exe()

    def initActions(self):
        self.exit_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'quit.png')), 'Quit', self)
        self.exit_action.setShortcut('Ctrl+Q')
        self.exit_action.setStatusTip('Exit application')
        self.exit_action.triggered.connect(self.close)

        self.data_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'new.png')), 'Data', self)
        self.data_action.setShortcut('Ctrl+D')
        self.data_action.setStatusTip('Managing Data')
        self.data_action.triggered.connect(self.open_data_config)

        self.compile_and_exe_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'run.png')),
            'Compile and Run', self)
        self.compile_and_exe_action.setShortcut('Ctrl+R')
        self.compile_and_exe_action.triggered.connect(self.compile_and_exe)
        self.compile_and_exe_action.setIconVisibleInMenu(True)
        self.addAction(self.compile_and_exe_action)

        self.load_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'load.png')), 'load', self)
        self.load_action.setShortcut('Ctrl+O')
        self.load_action.triggered.connect(self.load_graph)
        self.load_action.setIconVisibleInMenu(True)
        self.addAction(self.load_action)

        self.save_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'save.png')), 'save', self)
        self.save_action.setShortcut('Ctrl+S')
        self.save_action.triggered.connect(self.save_graph_and_train)
        self.save_action.setIconVisibleInMenu(True)
        self.addAction(self.save_action)

        self.clear_all_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'kill.png')),
            'Clear All', self)
        # self.killRunnerAction.setShortcut('Ctrl+K')
        self.clear_all_action.triggered.connect(self.clear_all_nodes)
        self.clear_all_action.setIconVisibleInMenu(True)
        self.addAction(self.clear_all_action)

        self.compile_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'unpause.png')),
            'Compile', self)
        self.compile_action.setShortcut('Ctrl+L')
        self.compile_action.triggered.connect(self.compile_runner)
        self.compile_action.setIconVisibleInMenu(True)
        self.addAction(self.compile_action)

        self.exe_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'step.png')), 'Run', self)
        self.exe_action.setShortcut('Ctrl+K')
        self.exe_action.triggered.connect(self.exe_runner)
        self.exe_action.setIconVisibleInMenu(True)
        self.addAction(self.exe_action)

        self.deleteNodeAction = QtWidgets.QAction('Delete', self)
        self.deleteNodeAction.setShortcut('Delete')
        self.deleteNodeAction.triggered.connect(self.deleteNode)
        self.deleteNodeAction.setIconVisibleInMenu(True)
        self.addAction(self.deleteNodeAction)

        self.copyNodeAction = QtWidgets.QAction('Copy', self)
        self.copyNodeAction.setShortcut('Ctrl+C')
        self.copyNodeAction.triggered.connect(self.copyNode)
        self.copyNodeAction.setIconVisibleInMenu(True)
        self.addAction(self.copyNodeAction)

        self.pasteNodeAction = QtWidgets.QAction('Paste', self)
        self.pasteNodeAction.setShortcut('Ctrl+V')
        self.pasteNodeAction.triggered.connect(self.pasteNode)
        self.pasteNodeAction.setIconVisibleInMenu(True)
        self.addAction(self.pasteNodeAction)

        self.undoAction = QtWidgets.QAction('Undo', self)
        self.undoAction.setShortcut('Ctrl+Z')
        self.undoAction.triggered.connect(self.undoGraph)
        self.undoAction.setIconVisibleInMenu(False)
        self.addAction(self.undoAction)

        self.statusAction = QtWidgets.QAction('Status', self)
        # self.statusAction.setShortcut('Ctrl+R')
        self.statusAction.triggered.connect(self.updateStatus)
        self.statusAction.setIconVisibleInMenu(True)
        self.addAction(self.statusAction)

        self.train_configure_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'drop.png')),
            'Train configuration', self)
        self.train_configure_action.setShortcut('Ctrl+I')
        self.train_configure_action.triggered.connect(self.open_train_config)
        self.train_configure_action.setIconVisibleInMenu(True)
        self.addAction(self.train_configure_action)

        self.prediction_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'push.png')),
            'Predict by trained model', self)
        self.prediction_action.setShortcut('Ctrl+P')
        self.prediction_action.triggered.connect(self.open_prediction)
        self.prediction_action.setIconVisibleInMenu(True)
        self.addAction(self.prediction_action)

        self.settings_action = QtWidgets.QAction(
            QtGui.QIcon(os.path.join(self.iconRoot, 'settings.png')),
            'Settings', self)
        self.settings_action.setShortcut('Ctrl+T')
        self.settings_action.triggered.connect(self.openSettingsDialog)
        self.settings_action.setIconVisibleInMenu(False)
        self.addAction(self.settings_action)

    def initMenus(self):
        fileMenu = self.menuBar.addMenu('&File')
        fileMenu.addAction(self.data_action)
        fileMenu.addAction(self.save_action)
        fileMenu.addAction(self.load_action)
        fileMenu.addAction(self.exit_action)

        run_menu = self.menuBar.addMenu('&Run')
        run_menu.addAction(self.compile_and_exe_action)
        run_menu.addAction(self.compile_action)
        run_menu.addAction(self.exe_action)

        settingsMenu = self.menuBar.addMenu('&Settings')
        settingsMenu.addAction(self.train_configure_action)
        settingsMenu.addAction(self.settings_action)

        self.mainToolBar.addWidget(self.select_data_button)
        self.mainToolBar.addSeparator()

        self.mainToolBar.addAction(self.save_action)
        self.mainToolBar.addAction(self.load_action)
        self.mainToolBar.addSeparator()

        self.mainToolBar.addAction(self.compile_and_exe_action)
        self.mainToolBar.addSeparator()

        self.mainToolBar.addAction(self.compile_action)
        self.mainToolBar.addAction(self.exe_action)
        self.mainToolBar.addSeparator()

        self.mainToolBar.addAction(self.prediction_action)
        self.mainToolBar.addAction(self.clear_all_action)
        self.mainToolBar.addSeparator()

        self.mainToolBar.addAction(self.train_configure_action)
        self.mainToolBar.addAction(self.settings_action)

    def open_data_config(self):
        if 'Image' in TrainParamServer()['Task']:
            try:
                import chainercv
                data_dialog = ImageDataDialog(self, settings=self.settings)
            except ImportError:
                util.disp_error('Failed to import chainercv.'
                                'See https://github.com/chainer/chainercv#installation')
                return
        else:
            data_dialog = DataDialog(self, settings=self.settings)
        data_dialog.show()
        self.update_data_label()

    def update_data_label(self):
        text = TrainParamServer().get_train_data_name()
        if text:
            self.select_data_button.setText('Selecting Data: ' + text)
        else:
            self.select_data_button.setText('Please Select Data File')

    def openSettingsDialog(self):
        SettingsDialog(self, settings=self.settings).show()

    def open_train_config(self):
        TrainDialog(self, settings=self.settings).show()

    def open_prediction(self):
        PredictionWindow(self, settings=self.settings).show()

    def connect(self):
        # TODO(fukatani): Implement.
        pass

    def close(self):
        try:
            self.drawer.graph.killRunner()
        except:
            util.disp_error('No runner to kill.')
        QtWidgets.qApp.quit()

    def updateStatus(self):
        try:
            self.drawer.graph.requestRemoteStatus()
        except AttributeError:
            self.statusBar.showMessage(
                'Cannot Update Graph. No Interpreter Available..', 2000)

    def killRunner(self):
        try:
            self.drawer.graph.killRunner()
        except ConnectionRefusedError:
            pass

    def deleteNode(self):
        node = self.drawer.getSelectedNode()
        if node:
            self.drawer.delete_node(node)

    def clear_all_nodes(self):
        self.drawer.clear_all_nodes()

    def copyNode(self):
        node = self.drawer.getSelectedNode()
        if node:
            self.drawer.copy_node(node)

    def pasteNode(self):
        self.drawer.paste_node()

    def undoGraph(self):
        self.drawer.undo_graph()

    def exe_runner(self):
        self.statusBar.showMessage('Run started.', 2000)
        self.drawer.graph.run()
        self.BottomWidget.update_report()

    def compile_runner(self):
        self.statusBar.showMessage('Compile started.', 2000)
        return self.drawer.graph.compile()

    def compile_and_exe(self):
        if self.compile_runner():
            self.exe_runner()
        else:
            util.disp_error('Compile is failured')

    def load_graph(self, override=''):
        if not override:
            init_path = TrainParamServer().get_work_dir()
            file_name = QtWidgets.QFileDialog.getOpenFileName(
                self, 'Open File', init_path,
                filter='Chainer Wing Files (*.json);; Any (*.*)')[0]
        else:
            file_name = override
        if not file_name:
            return
        logger.debug('Attempting to load graph: {}'.format(file_name))
        self.drawer.clear_all_nodes()
        with open(file_name, 'r') as fp:
            try:
                proj_dict = json.load(fp)
            except json.decoder.JSONDecodeError:
                util.disp_error(file_name + ' is corrupted.')
                return
            # proj_dict = json.load(fp, object_hook=util.nethook)
            if 'graph' in proj_dict:
                self.drawer.graph.load_from_dict(proj_dict['graph'])
                self.statusBar.showMessage(
                    'Graph loaded from {}.'.format(file_name), 2000)
                logger.info('Successfully loaded graph: {}'.format(file_name))
            if 'train' in proj_dict:
                TrainParamServer().load_from_dict(proj_dict['train'])
        self.settings.setValue('graph_file', file_name)
        self.update_data_label()
        self.setupNodeLib()
        TrainParamServer()['ProjectName'] = file_name.split('/')[-1].replace('.json', '')

    def save_graph_and_train(self, *args):
        """
        Callback for the 'SaveAction'.
        :param args: throwaway arguments.
        :return: None
        """
        file_name = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Save File', '~/',
            filter='Chainer Wing Files (*.json);; Any (*.*)')[0]
        if not file_name:
            return
        if not file_name.endswith('.json'):
            file_name += '.json'
        logger.debug('Attempting to save graph as {}'.format(file_name))
        with open(file_name, 'w') as fp:
            proj_dict = {'graph': self.drawer.graph.to_dict(),
                         'train': TrainParamServer().to_dict()}
            proj_dump = json.dumps(proj_dict, sort_keys=True, indent=4,
                                   cls=util.NetJSONEncoder)
            fp.write(proj_dump)
        self.statusBar.showMessage('Graph saved as {}.'.format(file_name), 2000)
        logger.info('Save graph as {}'.format(file_name))

    def resizeEvent(self, event):
        super(MainWindow, self).resizeEvent(event)
        self.drawer.repaint()
        self.drawer.update()

    def setupNodeLib(self):
        self.NodeListView.setup(self.FilterEdit, self.drawer.graph)

    def closeEvent(self, event):
        logger.debug('Attempting to kill interpreter.')
        self.killRunner()
        logger.debug('MainWindow is shutting down.')
        self.settings.setValue("size", self.size())
        self.settings.setValue("pos", self.pos())
        super(MainWindow, self).closeEvent(event)

    def keyPressEvent(self, event):
        super(MainWindow, self).keyPressEvent(event)
        if event.key() == 16777248:
            self.drawer.keyPressEvent(event)

    def keyReleaseEvent(self, event):
        super(MainWindow, self).keyReleaseEvent(event)
        if event.key() == 16777248:
            self.drawer.keyReleaseEvent(event)


class DrawItem(object):
    alignment = Qt.AlignRight

    def __init__(self, parent, data, painter):
        self.settings = painter.settings
        self.painter = painter
        self.state = False
        self.x = 0
        self.y = 0
        self.w = 0
        self.h = 0
        self.parent = parent
        self.data = data
        self.active = True

    def deactivate(self):
        self.active = False

    def activate(self):
        self.active = True

    def update(self, x, y, w, h, transform):
        self.transform = transform
        self.x = x
        self.y = y
        self.w = w - 10
        self.h = h
        point = QtCore.QPoint(x + 12, y - 16) * transform
        self._x = point.x()
        self._y = point.y()
        point = QtCore.QPoint(x + w - 24, y + h - 60) * transform
        self._xx = point.x()
        self._yy = point.y()

        self._yy = self._y + PINSIZE

    def draw(self, painter, as_label=''):
        alignment = self.__class__.alignment
        text = self.data.name
        pen = QtGui.QPen(Qt.darkGray)
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(40, 40, 40))
        xx, yy, ww, hh = self.x + self.w / 2. - (
            self.w - 25) / 2., self.y - 18, self.w - 18, 4 + PINSIZE
        self.set_font(painter)
        painter.setPen(pen)
        painter.drawText(xx + 5, yy - 3 + TEXTYOFFSET, ww - 10, hh + 5,
                         alignment, text)

    def set_font(self, painter):
        painter.setFont(
            QtGui.QFont('Helvetica', self.settings.value('FontSize')))

    def run(self):
        pass

    def collide(self, pos):
        if not self.active:
            return False
        if self._x < pos.x() < self._xx and self._y < pos.y() < self._yy:
            return True

    def watch(self, pos):
        pass

    def watchDown(self, pos):
        pass

    def keyPressEvent(self, event):
        pass


class Selector(DrawItem):
    alignment = Qt.AlignLeft

    def __init__(self, *args, **kwargs):
        super(Selector, self).__init__(*args, **kwargs)
        self.highlight = 0
        self.select = None
        self.items = self.data.info.select
        if self.data.info.has_value_set():
            self.select = str(self.data.info.value)

    def update(self, x, y, w, h, transform):
        super(Selector, self).update(x, y, w, h, transform)
        if self.select is not None:
            self.items = self.data.info.select
            if self.data.info.has_value_set():
                self.select = str(self.data.info.value)

    def watch(self, pos):
        scale = self.painter.scale
        for i in range(1, len(self.items) + 1):
            if self._x < pos.x() < self._xx and self._y + 4 * scale + PINSIZE * i * scale < pos.y() < (
                            self._y + 4 * scale + (i + 1) * scale * PINSIZE):
                self.highlight = i
                return

    def watchDown(self, pos):
        self.select = str(self.items[self.highlight - 1])
        self.parent.inputs[self.data.name].set_value_from_text(self.select)

    def collide(self, pos):
        if self._x < pos.x() < self._xx + 16 and self._y < pos.y() < self._yy:
            self.state = (self.state + 1) % 2
            try:
                self.painter.registerWatchingItem(self)
            except ValueError:
                pass
        else:
            if self.state:
                try:
                    self.painter.removeWatchingItem(self)
                except ValueError:
                    pass
            self.state = 0
        return super(Selector, self).collide(pos)

    def draw(self, painter, last=False, as_label=''):
        if as_label:
            text = as_label
            alignment = self.__class__.alignment
            pen = QtGui.QPen(Qt.darkGray)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(40, 40, 40))
            xx, yy, ww, hh = self.x + self.w / 2. - (
                self.w - 25) / 2., self.y - 18, self.w - 18, 4 + PINSIZE
            self.set_font(painter)
            painter.setPen(pen)
            painter.drawText(xx + 5, yy - 3 + TEXTYOFFSET, ww - 10, hh + 5,
                             alignment, text)
            return
        if not self.state:
            alignment = self.alignment
            text = self.data.name
            if self.select:
                text = str(self.select)
            pen = QtGui.QPen(Qt.darkGray)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(40, 40, 40))
            xx, yy, ww, hh = self.x + self.w / 2. - (
                self.w - 25) / 2., self.y - 18, self.w - 25, 4 + PINSIZE
            painter.drawRoundedRect(xx, yy, ww, hh, 2, 20)
            self.set_font(painter)
            painter.setPen(pen)
            painter.drawText(xx + 5, yy - 3 + TEXTYOFFSET, ww - 20, hh + 5,
                             alignment, text)
            pen.setColor(Qt.gray)
            # pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(Qt.gray))
            points = QtCore.QPoint(xx + self.w - 40, yy - 2 + PINSIZE / 2), \
                     QtCore.QPoint(xx + 10 - 40 + self.w, yy - 2 + PINSIZE / 2), \
                     QtCore.QPoint(xx + 5 + self.w - 40, yy + 4 + PINSIZE / 2)
            painter.drawPolygon(*points)
            painter.setBrush(QtGui.QColor(40, 40, 40))
        else:
            if not last:
                return self
            alignment = self.alignment
            text = self.data.name
            pen = QtGui.QPen(Qt.darkGray)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(40, 40, 40))
            xx, yy, ww, hh = self.x + self.w / 2. - (
                self.w - 25) / 2., self.y - 26 + 12, self.w - 25, (
                                 4 + PINSIZE) * len(self.items)
            painter.drawRoundedRect(xx, yy + PINSIZE, ww, hh, 2, 20 + PINSIZE)
            self.set_font(painter)
            painter.setPen(pen)

            for i, item in enumerate(self.items):
                item = str(item)
                if i + 1 == self.highlight:
                    pen.setColor(Qt.white)
                    painter.setPen(pen)
                else:
                    pen = QtGui.QPen(Qt.darkGray)
                    painter.setPen(pen)
                painter.drawText(xx + 5, yy + PINSIZE - 3 + i * (
                    4 + PINSIZE) + TEXTYOFFSET, ww - 20, hh + 5 + PINSIZE,
                                 alignment, item)

            pen = QtGui.QPen(Qt.darkGray)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(60, 60, 60))
            xx, yy, ww, hh = self.x + self.w / 2. - (
                self.w - 25) / 2., self.y - 18, self.w - 25, 4 + PINSIZE
            painter.drawRoundedRect(xx, yy, ww, hh, 2, 20)
            painter.drawText(xx + 5, yy - 3 + TEXTYOFFSET, ww - 20, hh + 5,
                             alignment, text)


class LineEdit(DrawItem):
    alignment = Qt.AlignLeft

    def __init__(self, parent, data, painter):
        super(LineEdit, self).__init__(parent, data, painter)
        self.text = ''

    def collide(self, pos):
        collides = super(LineEdit, self).collide(pos)
        if collides:
            self.state = (self.state + 1) % 2
            self.painter.registerWatchingItem(self)
            self.painter.relayInputEventsTo(self)
        else:
            self.painter.stopInputRelayingTo(self)
            if self.state:
                self.painter.removeWatchingItem(self)
            self.state = 0
        return collides

    def draw(self, painter, as_label=''):
        """
        :param as_label(str, optional):
            Override text contents. Mainly used for connected pins.
        """
        if as_label:
            text = as_label
        elif not self.text and not self.data.info.value:
            text = self.data.name + '()'
        elif self.state:  # if editting
            text = self.data.info.value
        else:
            text = self.data.name + '(' + str(self.data.info.value) + ')'
        text = str(text)
        alignment = self.__class__.alignment
        pen = QtGui.QPen(Qt.darkGray)
        painter.setPen(pen)
        xx, yy, ww, hh = self.x + self.w / 2. - (
            self.w - 25) / 2., self.y - 18, self.w - 18, 4 + PINSIZE
        if as_label:
            painter.setBrush(QtGui.QColor(40, 40, 40))
        elif not self.state:
            painter.setBrush(QtGui.QColor(40, 40, 40))
            painter.drawRoundedRect(xx, yy, ww, hh, 2, 20)
        else:
            painter.setBrush(QtGui.QColor(10, 10, 10))
            painter.drawRoundedRect(xx, yy, ww, hh, 2, 20)
        self.set_font(painter)
        painter.setPen(pen)
        painter.drawText(xx + 5, yy - 3 + TEXTYOFFSET, ww - 10, hh + 5,
                         alignment, text)

    def keyPressEvent(self, event):
        if event.key() == 16777219:  # Backspace
            self.text = self.text[:-1]
        else:
            self.text += self._sanitize_string(event.text())
        self.painter.update()
        self.parent.inputs[self.data.name].set_value_from_text(self.text)

    def _sanitize_string(self, string):
        string = string.strip('\r\n')
        try:
            if float in self.data.info.var_type and string == '.':
                string = '0.'
            self.data.info.convert_var_type(string)
        except ValueError:
            return ''
        return string


class InputLabel(DrawItem):
    alignment = Qt.AlignLeft


class OutputLabel(DrawItem):
    pass
