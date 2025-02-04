# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ZonalExact
                                 A QGIS plugin
 Zonal Statistics of rasters using Exact Extract library
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                             -------------------
        begin                : 2024-02-11
        copyright            : (C) 2024 by Jakub Charyton
        email                : jakub.charyton@gmail.com
        git sha              : $Format:%H$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load ZonalExact class from file ZonalExact.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .zonal_exact import ZonalExact
    return ZonalExact(iface)
