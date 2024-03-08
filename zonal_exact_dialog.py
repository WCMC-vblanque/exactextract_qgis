# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ZonalExactDialog
                                 A QGIS plugin
 Zonal Statistics of rasters using Exact Extract library
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2024-02-11
        git sha              : $Format:%H$
        copyright            : (C) 2024 by Jakub Charyton
        email                : jakub.charyton@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
from typing import List
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsMapLayerProxyModel, QgsFieldProxyModel, QgsTask, QgsApplication, QgsTaskManager, QgsMessageLog, QgsVectorLayer, 
                    QgsField, edit, QgsFeatureRequest)

import geopandas as gpd
import pandas as pd

from .dialog_input_dto import DialogInputDTO
from .user_communication import UserCommunication, WidgetPlainTextWriter
from .task_classes import CalculateStatsTask, PostprocessStatsTask

# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'zonal_exact_dialog_base.ui'))


class ZonalExactDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None, uc: UserCommunication = None, iface = None, project = None, task_manager: QgsTaskManager = None):
        """Constructor."""
        super(ZonalExactDialog, self).__init__(parent)
        # Set up the user interface from Designer through FORM_CLASS.
        # After self.setupUi() you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        # Initiate  a new instance of the dialog input DTO class to hold all input data
        self.dialog_input: DialogInputDTO = None
        # Initiate an empty list for storing tasks in queue
        self.tasks = []
        # Initiate an empty list to store intermediate results of zonal statistics calculation
        self.intermediate_result_list = []
        # Initiate main task that will hold aggregated data from child calculating tasks
        self.postprocess_task: PostprocessStatsTask = None
        self.input_gdf: gpd.GeoDataFrame = None
        self.calculated_stats_list = []
        self.temp_index_field = None
        self.features_count = None
        # assign qgis internal variables to class variables
        self.uc = uc
        self.iface = iface
        self.project = project
        self.task_manager: QgsTaskManager = task_manager
        
        self.setupUi(self)
        
        self.widget_console = WidgetPlainTextWriter(self.mPlainText)
        
        # controls whether output file is virtual or saved on disk
        self.flag_virtual = False
        self.mVirtualCheckBox.setChecked(self.flag_virtual)
        self.mQgsOutputFileWidget.setFileWidgetButtonVisible(not self.flag_virtual)
        self.mQgsOutputFileWidget.setReadOnly(self.flag_virtual)
        self.mVirtualCheckBox.clicked.connect(self.toggle_virtual)
        # set filters on combo boxes to get correct layer types
        self.mRasterLayerComboBox.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.mVectorLayerComboBox.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        # set ID field combo box to current vector layer
        self.mFieldComboBox.setFilters(QgsFieldProxyModel.LongLong | QgsFieldProxyModel.Int)
        if self.mVectorLayerComboBox.currentLayer():
            self.mFieldComboBox.setLayer(self.mVectorLayerComboBox.currentLayer())
        self.mVectorLayerComboBox.layerChanged.connect(self.set_field_vector_layer)
        # set temp_index_field class variable when user selects another index field
        if self.mFieldComboBox.currentField():
            self.temp_index_field = self.mFieldComboBox.currentField()
        self.mFieldComboBox.fieldChanged.connect(self.set_id_field)
        
        self.mCalculateButton.clicked.connect(self.calculate)

    def set_field_vector_layer(self):
        selectedLayer = self.mVectorLayerComboBox.currentLayer()
        if selectedLayer:
            self.mFieldComboBox.setLayer(selectedLayer)
    
    def set_id_field(self):
        self.temp_index_field = self.mFieldComboBox.currentField()
    
    def calculate(self):
        self.mCalculateButton.setEnabled(False)
        try:
            self.get_input_values()  # loads input values from the dialog into self.dialog_input
            if self.dialog_input is None:
                self.mCalculateButton.setEnabled(True)
                return
            self.input_vector: QgsVectorLayer = self.dialog_input.vector_layer
            
            self.features_count = self.input_vector.featureCount()
            batch_size = round(self.features_count / self.dialog_input.parallel_jobs)
            # calculate using QgsTask and exactextract
            self.process_calculations(self.input_vector, batch_size)
            # wait for calculations to finish to continue
            if self.postprocess_task is not None:
                self.postprocess_task.taskCompleted.connect(self.save_result)
        except Exception as exc:
            QgsMessageLog.logMessage(f'ERROR: {exc}')
            self.widget_console.write_error(exc)
        finally:
            self.mCalculateButton.setEnabled(True)
            
    def process_calculations(self, vector_gdf, batch_size):
        self.intermediate_result_list = []
        self.postprocess_task = PostprocessStatsTask(f'Zonal ExactExtract task', QgsTask.CanCancel, widget_console=self.widget_console,
                                                    result_list=self.intermediate_result_list,
                                                    index_column=self.temp_index_field, prefix=self.dialog_input.prefix)
        self.postprocess_task.taskCompleted.connect(self.update_progress_bar)
        
        self.tasks = []
        for i in range(0, self.features_count, batch_size):
            selection_ids = list(range(i, i + batch_size))
            self.input_vector.selectByIds(selection_ids)
            temp_vector = self.input_vector.materialize(QgsFeatureRequest().setFilterFids(self.input_vector.selectedFeatureIds()))
            
            calculation_subtask = CalculateStatsTask(f'calculation subtask {i}', flags=QgsTask.Silent, result_list=self.intermediate_result_list,
                                                    widget_console=self.widget_console,
                                                    polygon_layer=temp_vector, raster=self.dialog_input.raster_layer_path,
                                                    stats=self.dialog_input.aggregates_stats_list+self.dialog_input.arrays_stats_list,
                                                    include_cols=[self.temp_index_field])
            calculation_subtask.taskCompleted.connect(self.update_progress_bar)
            self.tasks.append(calculation_subtask)
            self.postprocess_task.addSubTask(calculation_subtask, [], QgsTask.ParentDependsOnSubTask)

        self.task_manager.addTask(self.postprocess_task)
        
    def save_result(self):
        calculated_stats_df = self.postprocess_task.calculated_stats
        QgsMessageLog.logMessage(f'Zonal ExactExtract task result shape: {str(calculated_stats_df.shape)}')
        self.widget_console.write_info(f'Zonal ExactExtract task result shape: {str(calculated_stats_df.shape)}')
        
        
        
        try:
            polygon_layer_stats_gdf = pd.merge(self.input_gdf, calculated_stats_df, on=self.temp_index_field, how='left')
            if self.flag_virtual:
                virtual_layer = QgsVectorLayer(polygon_layer_stats_gdf.to_json(),"result_zonal_layer","memory")
                self.project.addMapLayer(virtual_layer)
            else:
                polygon_layer_stats_gdf.to_file(self.dialog_input.output_file_path, engine='pyogrio')
                # Create a QgsVectorLayer instance for the GeoPackage
                output_project_layer = QgsVectorLayer(self.dialog_input.output_file_path, Path(self.dialog_input.output_file_path).stem, 'ogr')

                # Check if the layer was loaded successfully
                if not output_project_layer.isValid():
                    QgsMessageLog.logMessage(f'Unable to load layer from {self.dialog_input.output_file_path}')
                    self.widget_console.write_error(f'Unable to load layer from {self.dialog_input.output_file_path}')
                else:
                    self.widget_console.write_info('Finished calculating statistics')
                    # Add the layer to the project
                    self.project.addMapLayer(output_project_layer)
                    
        except Exception as exc:
            QgsMessageLog.logMessage(f'ERROR: {exc}')
            self.widget_console.write_error(exc)
        finally:
            self.clean()
            self.mCalculateButton.setEnabled(True)

    def update_progress_bar(self):
        # calculate progress change as percentage of total tasks completed + parent task
        progress_change = int((1 / (len(self.tasks) + 1)) * 100)
        self.mProgressBar.setValue(self.mProgressBar.value() + progress_change)
        
    def clean(self):
        # reinitialize object values to free memory after calculation is done
        self.dialog_input: DialogInputDTO = None
        self.tasks = []
        self.intermediate_result_list = []
        self.postprocess_task: PostprocessStatsTask = None
        self.input_gdf: gpd.GeoDataFrame = None
        self.calculated_stats_list = []
        
        self.mProgressBar.setValue(0)
        
    def get_input_values(self):
        raster_layer_path: str = self.mRasterLayerComboBox.currentLayer().dataProvider().dataSourceUri()
        vector_layer: QgsVectorLayer = self.mVectorLayerComboBox.currentLayer()
        parallel_jobs: int = self.mSpinBox.value()
        output_file_path: str = self.mQgsOutputFileWidget.filePath()
        aggregates_stats_list: List[str] = self.mAggregatesComboBox.checkedItems()
        arrays_stats_list: List[str] = self.mArraysComboBox.checkedItems()
        prefix: str = self.mPrefixEdit.text()
        # check if both raster and vector layers are set
        if not raster_layer_path or not vector_layer:
            self.uc.bar_warn(f"You didn't select raster layer or vector layer")
            return
        # check if ID field is set
        if not self.temp_index_field:
            self.uc.bar_warn(f"You didn't select ID field")
            return
        # check if ID field is unique
        # TODO: Checking uniqueness would require a looping over all features  in the vector layer, which can be slow
        # therefore it is omitted for now until we have a better solution
        # We might add a checkbox to let user decide wether we should check uniqueness (with given information that it might be slow operation)
        if not self.flag_virtual and not output_file_path:
            self.uc.bar_warn(f"You didn't select output file path")
            return
        # check if both stats lists are empty
        if not aggregates_stats_list and not arrays_stats_list:
            self.uc.bar_warn(f"You didn't select anything from either Aggregates and Arrays")
            return
        
        self.dialog_input = DialogInputDTO(raster_layer_path=raster_layer_path, vector_layer=vector_layer, parallel_jobs=parallel_jobs, 
                                        output_file_path=output_file_path, aggregates_stats_list=aggregates_stats_list, arrays_stats_list=arrays_stats_list,
                                        prefix=prefix)
                    
    def toggle_virtual(self):
        self.flag_virtual = not self.flag_virtual
        self.mVirtualCheckBox.setChecked(self.flag_virtual)
        self.mQgsOutputFileWidget.setFileWidgetButtonVisible(not self.flag_virtual)
        self.mQgsOutputFileWidget.setReadOnly(self.flag_virtual)
        
    # def run(self):
    #     QgsMessageLog.logMessage(f'Inside Postprocess Task: {self.description}')
    #     self.widget_console.write_info(f'Inside Postprocess Task: {self.description}')
        
    #     # result_indexed_list = [df.set_index(self.index_column) for df in self.result_list]
    #     calculated_stats = pd.concat(self.result_list)
        
    #     if self.index_column is not None and self.index_column_dtype is not None:
    #         # change index dtype to dtype of index column in input layer
    #         index_dtype = str(self.index_column_dtype)
    #         calculated_stats = calculated_stats.astype({self.index_column:index_dtype})
        
    #     if len(self.prefix) > 0:
    #         # rename columns to include prefix string
    #         rename_dict = {column: f"{self.prefix}_{column}" for column in calculated_stats.columns if column != self.index_column}
    #         calculated_stats = calculated_stats.rename(columns=rename_dict)
        
    #     self.calculated_stats = calculated_stats

