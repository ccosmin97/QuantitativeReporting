import getpass
import json

from slicer.ScriptedLoadableModule import *
import vtkSegmentationCorePython as vtkCoreSeg

from SlicerProstateUtils.mixins import *
from SlicerProstateUtils.decorators import logmethod
from SlicerProstateUtils.helpers import WatchBoxAttribute, DICOMBasedInformationWatchBox
from SlicerProstateUtils.constants import DICOMTAGS

from SegmentEditor import SegmentEditorWidget
from LabelStatistics import LabelStatisticsLogic


class Reporting(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Reporting" # TODO make this more human readable by adding spaces
    self.parent.categories = ["Examples"]
    self.parent.dependencies = ["SlicerProstate"]
    self.parent.contributors = ["Andrey Fedorov (SPL, BWH), Nicole Aucoin (SPL, BWH), "
                                "Steve Pieper (Isomics), Christian Herz (SPL)"]
    self.parent.helpText = """
    This is an example of scripted loadable module bundled in an extension.
    It performs a simple thresholding on the input volume and optionally captures a screenshot.
    """
    self.parent.acknowledgementText = """
    This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc.
    and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""" # replace with organization, grant and thanks.


class ReportingWidget(ModuleWidgetMixin, ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  @property
  def segmentation(self):
    try:
      return self.segNode.GetSegmentation()
    except AttributeError:
      return None

  def __init__(self, parent=None):
    ScriptedLoadableModuleWidget.__init__(self, parent)
    self.logic = ReportingLogic()
    self.segmentationsLogic = slicer.modules.segmentations.logic()
    self.segReferencedMasterVolume = {} # TODO: maybe also add created table so that there is no need to recalculate everything?

  def initializeMembers(self):
    self.tNode = None
    self.tableNode = None
    self.segNode = None
    self.displayTableInSliceView = False
    self.segmentationObservers = []
    self.segmentationLabelMapDummy = None

  def onReload(self):
    super(ReportingWidget, self).onReload()
    self.cleanup()

  def cleanup(self):
    self.removeSegmentationObserver()
    self.removeConnections()
    if self.tableNode:
      slicer.mrmlScene.RemoveNode(self.tableNode)
    self.initializeMembers()

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    self.initializeMembers()
    self.setupWatchbox()
    self.setupSelectionArea()
    self.setupViewSettingsArea()
    self.setupSegmentationsArea()
    self.setupMeasurementsArea()
    self.setupActionButtons()
    self.setupConnections()
    self.layout.addStretch(1)

  def setupWatchbox(self):
    self.watchBoxInformation = [
      WatchBoxAttribute('StudyID', 'Study ID: ', DICOMTAGS.STUDY_ID),
      WatchBoxAttribute('PatientName', 'Patient Name: ', DICOMTAGS.PATIENT_NAME),
      WatchBoxAttribute('DOB', 'Date of Birth: ', DICOMTAGS.PATIENT_BIRTH_DATE),
      WatchBoxAttribute('Reader', 'Reader Name: ', callback=getpass.getuser)]
    self.watchBox = DICOMBasedInformationWatchBox(self.watchBoxInformation)
    self.layout.addWidget(self.watchBox)

  def setupSelectionArea(self):
    self.imageVolumeSelector = self.createComboBox(nodeTypes=["vtkMRMLScalarVolumeNode", ""], showChildNodeTypes=False,
                                                   selectNodeUponCreation=True, toolTip="Select image volume to annotate")
    self.imageVolumeSelector.addAttribute("vtkMRMLScalarVolumeNode", "DICOM.instanceUIDs", None)
    self.measurementReportSelector = self.createComboBox(nodeTypes=["vtkMRMLTableNode", ""], showChildNodeTypes=False,
                                                         selectNodeUponCreation=True, toolTip="Select measurement report")
    self.imageVolumeSelector.addAttribute("vtkMRMLTableNode", "Reporting", None)
    self.selectionAreaWidget = qt.QWidget()
    self.selectionAreaWidgetLayout = qt.QGridLayout()
    self.selectionAreaWidget.setLayout(self.selectionAreaWidgetLayout)

    self.selectionAreaWidgetLayout.addWidget(qt.QLabel("Image volume to annotate"), 0, 0)
    self.selectionAreaWidgetLayout.addWidget(self.imageVolumeSelector, 0, 1)
    self.selectionAreaWidgetLayout.addWidget(qt.QLabel("Measurement report"), 1, 0)
    self.selectionAreaWidgetLayout.addWidget(self.measurementReportSelector, 1, 1)
    self.layout.addWidget(self.selectionAreaWidget)

  def setupViewSettingsArea(self):
    pass

  def setupSegmentationsArea(self):
    self.segmentationWidget = qt.QGroupBox("Segmentations")
    self.segmentationWidgetLayout = qt.QFormLayout()
    self.segmentationWidget.setLayout(self.segmentationWidgetLayout)
    self.editorWidget = ReportingSegmentEditorWidget(parent=self.segmentationWidget)
    self.editorWidget.setup()
    self.layout.addWidget(self.segmentationWidget)

  def setupMeasurementsArea(self):
    self.measurementsWidget = qt.QGroupBox("Measurements")
    self.measurementsWidgetLayout = qt.QVBoxLayout()
    self.measurementsWidget.setLayout(self.measurementsWidgetLayout)
    self.tableView = slicer.qMRMLTableView()
    self.tableView.minimumHeight = 150
    self.measurementsWidgetLayout.addWidget(self.tableView)
    self.layout.addWidget(self.measurementsWidget)

  def setupActionButtons(self):
    self.saveReportButton = self.createButton("Save Report")
    self.completeReportButton = self.createButton("Complete Report")
    self.layout.addWidget(self.createHLayout([self.saveReportButton, self.completeReportButton]))

  def setupConnections(self, funcName="connect"):

    def setupSelectorConnections():
      getattr(self.imageVolumeSelector, funcName)('currentNodeChanged(vtkMRMLNode*)', self.onImageVolumeSelectorChanged)

    def setupButtonConnections():
      getattr(self.saveReportButton.clicked, funcName)(self.onSaveReportButtonClicked)
      getattr(self.completeReportButton.clicked, funcName)(self.onCompleteReportButtonClicked)

    setupSelectorConnections()
    setupButtonConnections()

  def removeConnections(self):
    self.setupConnections(funcName="disconnect")

  def setupSegmentationObservers(self):
    if self.segmentation:
      self.segmentationObservers.append(self.segmentation.AddObserver(vtkCoreSeg.vtkSegmentation.SegmentAdded,
                                                                      self.onSegmentationNodeChanged))
      self.segmentationObservers.append(self.segmentation.AddObserver(vtkCoreSeg.vtkSegmentation.SegmentRemoved,
                                                                      self.onSegmentationNodeChanged))
      self.segmentationObservers.append(self.segmentation.AddObserver(vtkCoreSeg.vtkSegmentation.MasterRepresentationModified,
                                                                      self.onSegmentationNodeChanged))

  def removeSegmentationObserver(self):
    if self.segmentation and len(self.segmentationObservers):
      for observer in self.segmentationObservers:
        self.segmentation.RemoveObserver(observer)
      self.segmentationObservers = []
    self.segNode = None

  def onImageVolumeSelectorChanged(self, node):
    # TODO: save, cleanup open sessions
    self.removeSegmentationObserver()
    self.initializeWatchBox(node)
    if node:
      if node in self.segReferencedMasterVolume.keys():
        self.editorWidget.editor.setSegmentationNode(self.segNode)
      else:
        self.segReferencedMasterVolume[node] = self.createNewSegmentation(node)
      self.segNode = self.segReferencedMasterVolume[node]
      self.setupSegmentationObservers()
    else:
      self.clearSegmentationEditorSelectors()

  def initializeWatchBox(self, node):
    try:
      dicomFileName = node.GetStorageNode().GetFileName()
      self.watchBox.sourceFile = dicomFileName if os.path.exists(dicomFileName) else None
    except AttributeError:
      self.watchBox.sourceFile = None

  def createNewSegmentation(self, masterNode):
    segNode = slicer.vtkMRMLSegmentationNode()
    slicer.mrmlScene.AddNode(segNode)
    self.editorWidget.editor.setSegmentationNode(segNode)
    self.editorWidget.editor.setMasterVolumeNode(masterNode)
    return segNode

  @logmethod()
  def onSegmentationNodeChanged(self, observer=None, caller=None):
    if self.segmentationLabelMapDummy:
      slicer.mrmlScene.RemoveNode(self.segmentationLabelMapDummy)
    self.segmentationLabelMapDummy = slicer.vtkMRMLLabelMapVolumeNode()
    slicer.mrmlScene.AddNode(self.segmentationLabelMapDummy)
    if self.tableNode and self.tableNode.GetID() == self.logic.getActiveSlicerTableID():
      slicer.mrmlScene.RemoveNode(self.tableNode)
    if self.segmentationsLogic.ExportAllSegmentsToLabelmapNode(self.segNode, self.segmentationLabelMapDummy):
      grayscaleNode = self.segReferencedMasterVolume.keys()[self.segReferencedMasterVolume.values().index(self.segNode)]
      try:
        if self.tableNode:
          slicer.mrmlScene.RemoveNode(self.tableNode)
        self.tableNode = self.logic.calculateLabelStatistics(self.segmentationLabelMapDummy, grayscaleNode)
        self.tableView.setMRMLTableNode(self.tableNode)
        if self.displayTableInSliceView:
          slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
          slicer.app.applicationLogic().GetSelectionNode().SetReferenceActiveTableID(self.tableNode.GetID())
          slicer.app.applicationLogic().PropagateTableSelection()
      except ValueError as exc:
        slicer.util.warnDisplay(exc.message, windowTitle="Label Statistics")
    else:
      self.tableView.setMRMLTableNode(None)

  def onSaveReportButtonClicked(self):
    print "on save report button clicked"

  def onCompleteReportButtonClicked(self):
    print "on complete report button clicked"

  def onAnnotationReady(self):
    #TODO: calc measurements (logic) and set table node
    pass


class ReportingLogic(ScriptedLoadableModuleLogic):
  """This class should implement all the actual
  computation done by your module.  The interface
  should be such that other python code can import
  this class and make use of the functionality without
  requiring an instance of the Widget.
  Uses ScriptedLoadableModuleLogic base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent=None):
    ScriptedLoadableModuleLogic.__init__(self, parent)
    self.volumesLogic = slicer.modules.volumes.logic()

  def calculateLabelStatistics(self, labelNode, grayscaleNode):
    warnings = self.volumesLogic.CheckForLabelVolumeValidity(grayscaleNode, labelNode)
    if warnings != "":
      if 'mismatch' in warnings:
        resampledLabelNode = self.volumesLogic.ResampleVolumeToReferenceVolume(labelNode, grayscaleNode)
        # resampledLabelNode does not have a display node, therefore the colorNode has to be passed to it
        labelStatisticsLogic = LabelStatisticsLogic(grayscaleNode, resampledLabelNode,
                                                    colorNode=labelNode.GetDisplayNode().GetColorNode(),
                                                    nodeBaseName=labelNode.GetName())
      else:
        raise ValueError("Volumes do not have the same geometry.\n%s" % warnings)
    else:
      labelStatisticsLogic = LabelStatisticsLogic(grayscaleNode, labelNode)

    # TODO: manually pick information from labelStatisticsLogic.labelStats

    tableNode = labelStatisticsLogic.exportToTable()
    tableNode.SetAttribute("Reporting", "Yes")
    slicer.mrmlScene.AddNode(tableNode)
    return tableNode

  def getActiveSlicerTableID(self):
    return slicer.app.applicationLogic().GetSelectionNode().GetActiveTableID()


class ReportingTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_Reporting1()

  def test_Reporting1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")
    #
    # first, get some data
    #
    import urllib
    downloads = (
        ('http://slicer.kitware.com/midas3/download?items=5767', 'FA.nrrd', slicer.util.loadVolume),
        )

    for url,name,loader in downloads:
      filePath = slicer.app.temporaryPath + '/' + name
      if not os.path.exists(filePath) or os.stat(filePath).st_size == 0:
        logging.info('Requesting download %s from %s...\n' % (name, url))
        urllib.urlretrieve(url, filePath)
      if loader:
        logging.info('Loading %s...' % (name,))
        loader(filePath)
    self.delayDisplay('Finished with download and loading')

    volumeNode = slicer.util.getNode(pattern="FA")
    logic = ReportingLogic()
    self.assertIsNotNone( logic.hasImageData(volumeNode) )
    self.delayDisplay('Test passed!')


class ReportingSegmentEditorWidget(SegmentEditorWidget, ModuleWidgetMixin):

  def __init__(self, parent):
    super(ReportingSegmentEditorWidget, self).__init__(parent)

  def setup(self):
    super(ReportingSegmentEditorWidget, self).setup()
    self.reloadCollapsibleButton.hide()
    self.hideUnwantedEditorUIElements()
    self.reorganizeEffectButtons()
    self.clearSegmentationEditorSelectors()
    self.setupConnections()

  def setupConnections(self):
    segmentsTableView = slicer.util.findChildren(self.editor, "SegmentsTableView")[0]
    segmentsTableView.selectionChanged.connect(self.onSegmentSelected)

  def onSegmentSelected(self, item):
    try:
      # TODO: center on the segmentation
      print item.indexes()[0]
    except IndexError:
      pass

  def clearSegmentationEditorSelectors(self):
    self.editor.setSegmentationNode(None)
    self.editor.setMasterVolumeNode(None)

  def hideUnwantedEditorUIElements(self):
    self.editor.segmentationNodeSelectorVisible = False
    self.editor.masterVolumeNodeSelectorVisible = False
    for widgetName in ["OptionsGroupBox", "MaskingGroupBox"]:
      widget = slicer.util.findChildren(self.editor, widgetName)[0]
      widget.hide()

  def reorganizeEffectButtons(self):
    widget = slicer.util.findChildren(self.editor, "EffectsGroupBox")[0]
    if widget:
      buttons = [b for b in widget.children() if isinstance(b, qt.QPushButton)]
      self.layout.addWidget(self.createHLayout(buttons))
      widget.hide()
    undo = slicer.util.findChildren(self.editor, "UndoButton")[0]
    redo = slicer.util.findChildren(self.editor, "RedoButton")[0]
    if undo and redo:
      undo.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
      redo.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
      self.layout.addWidget(self.createHLayout([undo, redo]))

  def enter(self):
    # overridden because SegmentEditorWidget automatically creates a new Segmentation upon instantiation
    self.turnOffLightboxes()
    self.installShortcutKeys()

    # Set parameter set node if absent
    self.selectParameterNode()
    self.editor.updateWidgetFromMRML()