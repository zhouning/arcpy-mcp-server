def _count(arcpy, dataset):
    return int(arcpy.management.GetCount(dataset)[0])


def inspect_dataset(arcpy, parameters):
    described = arcpy.Describe(parameters["input_path"])
    fields = [
        {
            "name": field.name,
            "type": field.type,
            "length": field.length,
        }
        for field in arcpy.ListFields(parameters["input_path"])
    ]
    extent = getattr(described, "extent", None)
    spatial_reference = getattr(
        described, "spatialReference", None
    )
    return {
        "data_type": described.dataType,
        "name": described.baseName,
        "count": _count(arcpy, parameters["input_path"]),
        "fields": fields,
        "extent": (
            {
                "xmin": extent.XMin,
                "ymin": extent.YMin,
                "xmax": extent.XMax,
                "ymax": extent.YMax,
            }
            if extent
            else None
        ),
        "spatial_reference": (
            spatial_reference.name if spatial_reference else None
        ),
    }


def buffer_features(arcpy, parameters):
    arcpy.analysis.Buffer(
        parameters["input_path"],
        parameters["output_path"],
        parameters["distance"],
        dissolve_option=parameters.get("dissolve_option", "NONE"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def clip_features(arcpy, parameters):
    arcpy.analysis.Clip(
        parameters["input_path"],
        parameters["clip_path"],
        parameters["output_path"],
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def dissolve_features(arcpy, parameters):
    arcpy.management.Dissolve(
        parameters["input_path"],
        parameters["output_path"],
        parameters.get("dissolve_fields", []),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def intersect_features(arcpy, parameters):
    arcpy.analysis.Intersect(
        parameters["inputs"],
        parameters["output_path"],
        parameters.get("join_attributes", "ALL"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def union_features(arcpy, parameters):
    arcpy.analysis.Union(
        parameters["inputs"],
        parameters["output_path"],
        gaps=parameters.get("gaps", "GAPS"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def spatial_join(arcpy, parameters):
    arcpy.analysis.SpatialJoin(
        parameters["target_path"],
        parameters["join_path"],
        parameters["output_path"],
        join_operation=parameters.get(
            "join_operation", "JOIN_ONE_TO_ONE"
        ),
        match_option=parameters.get("match_option", "INTERSECT"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def project_features(arcpy, parameters):
    kwargs = {}
    if parameters.get("geographic_transform"):
        kwargs["transform_method"] = parameters["geographic_transform"]
    arcpy.management.Project(
        parameters["input_path"],
        parameters["output_path"],
        parameters["output_spatial_reference"],
        **kwargs,
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def merge_features(arcpy, parameters):
    arcpy.management.Merge(
        parameters["inputs"], parameters["output_path"]
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def check_geometry(arcpy, parameters):
    arcpy.management.CheckGeometry(
        parameters["input_path"],
        parameters["output_path"],
        parameters.get("validation_method", "ESRI"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def repair_geometry(arcpy, parameters):
    arcpy.management.CopyFeatures(
        parameters["input_path"], parameters["output_path"]
    )
    arcpy.management.RepairGeometry(
        parameters["output_path"],
        parameters.get("delete_null", "DELETE_NULL"),
        parameters.get("validation_method", "ESRI"),
    )
    return {
        "outputs": [parameters["output_path"]],
        "count": _count(arcpy, parameters["output_path"]),
    }


def checked_out_extension(arcpy, name):
    class Extension:
        def __enter__(self):
            status = arcpy.CheckExtension(name)
            if status not in {"Available", "CheckedOut"}:
                raise RuntimeError(f"{name} extension is unavailable")
            if status == "Available":
                arcpy.CheckOutExtension(name)
                self.checked_out = True
            else:
                self.checked_out = False

        def __exit__(self, exc_type, exc, traceback):
            if self.checked_out:
                arcpy.CheckInExtension(name)

    return Extension()


def clip_raster(arcpy, parameters):
    arcpy.management.Clip(
        parameters["input_path"],
        "#",
        parameters["output_path"],
        parameters["template_path"],
        "#",
        (
            "ClippingGeometry"
            if parameters.get("clipping_geometry", True)
            else "NONE"
        ),
    )
    return {"outputs": [parameters["output_path"]]}


def project_raster(arcpy, parameters):
    arcpy.management.ProjectRaster(
        parameters["input_path"],
        parameters["output_path"],
        parameters["output_spatial_reference"],
        parameters.get("resampling_type", "NEAREST"),
        parameters.get("cell_size"),
    )
    return {"outputs": [parameters["output_path"]]}


def resample_raster(arcpy, parameters):
    arcpy.management.Resample(
        parameters["input_path"],
        parameters["output_path"],
        parameters["cell_size"],
        parameters.get("resampling_type", "NEAREST"),
    )
    return {"outputs": [parameters["output_path"]]}


def extract_by_mask(arcpy, parameters):
    with checked_out_extension(arcpy, "Spatial"):
        result = arcpy.sa.ExtractByMask(
            parameters["input_path"], parameters["mask_path"]
        )
        result.save(parameters["output_path"])
    return {"outputs": [parameters["output_path"]]}


def slope(arcpy, parameters):
    with checked_out_extension(arcpy, "Spatial"):
        result = arcpy.sa.Slope(
            parameters["input_path"],
            parameters.get("output_measurement", "DEGREE"),
            parameters.get("z_factor", 1),
            analysis_target_device="CPU_ONLY",
        )
        result.save(parameters["output_path"])
    return {"outputs": [parameters["output_path"]]}


def zonal_statistics(arcpy, parameters):
    with checked_out_extension(arcpy, "Spatial"):
        arcpy.sa.ZonalStatisticsAsTable(
            parameters["zone_path"],
            parameters["zone_field"],
            parameters["value_path"],
            parameters["output_path"],
            statistics_type=parameters.get("statistics_type", "ALL"),
        )
    return {"outputs": [parameters["output_path"]]}


def mosaic_rasters(arcpy, parameters):
    from pathlib import Path

    output_path = Path(parameters["output_path"])
    arcpy.management.MosaicToNewRaster(
        parameters["inputs"],
        str(output_path.parent),
        output_path.name,
        parameters["coordinate_system"],
        parameters.get("pixel_type", "8_BIT_UNSIGNED"),
        number_of_bands=parameters.get("number_of_bands", 1),
    )
    return {"outputs": [parameters["output_path"]]}


def inspect_aprx(arcpy, parameters):
    project = arcpy.mp.ArcGISProject(parameters["aprx_path"])
    return {
        "maps": [item.name for item in project.listMaps()],
        "layouts": [item.name for item in project.listLayouts()],
    }


def export_layout(arcpy, parameters):
    project = arcpy.mp.ArcGISProject(parameters["aprx_path"])
    layouts = [
        item
        for item in project.listLayouts()
        if item.name == parameters["layout_name"]
    ]
    if len(layouts) != 1:
        raise ValueError("layout_name must match exactly one layout")
    if parameters["format"] == "PDF":
        layouts[0].exportToPDF(
            parameters["output_path"],
            resolution=parameters.get("dpi", 300),
        )
    else:
        layouts[0].exportToPNG(
            parameters["output_path"],
            resolution=parameters.get("dpi", 300),
        )
    return {"outputs": [parameters["output_path"]]}


def detect_objects(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.DetectObjectsUsingDeepLearning(
            parameters["input_path"],
            parameters["output_path"],
            parameters["model_path"],
            parameters.get("arguments", ""),
            parameters.get("run_nms", "NMS"),
            parameters.get("confidence_score_field", "Confidence"),
            parameters.get("class_value_field", "Class"),
            parameters.get("max_overlap_ratio", 0),
            "PROCESS_AS_MOSAICKED_IMAGE",
        )
    return {"outputs": [parameters["output_path"]]}


def classify_pixels(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        result = arcpy.ia.ClassifyPixelsUsingDeepLearning(
            parameters["input_path"],
            parameters["model_path"],
            parameters.get("arguments", ""),
            "PROCESS_AS_MOSAICKED_IMAGE",
        )
        result.save(parameters["output_path"])
    return {"outputs": [parameters["output_path"]]}


def classify_objects(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.ClassifyObjectsUsingDeepLearning(
            parameters["input_path"],
            parameters["output_path"],
            parameters["model_path"],
            model_arguments=parameters.get("arguments", ""),
        )
    return {"outputs": [parameters["output_path"]]}


def detect_change(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        result = arcpy.ia.DetectChangeUsingDeepLearning(
            parameters["from_path"],
            parameters["to_path"],
            parameters["model_path"],
            parameters.get("arguments", ""),
        )
        result.save(parameters["output_path"])
    return {"outputs": [parameters["output_path"]]}


def translate_pixels(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        result = arcpy.ia.TranslatePixelsUsingDeepLearning(
            parameters["input_path"],
            parameters["model_path"],
            parameters.get("arguments", ""),
            "PROCESS_AS_MOSAICKED_IMAGE",
        )
        result.save(parameters["output_path"])
    return {"outputs": [parameters["output_path"]]}


def export_training_data(arcpy, parameters):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.ExportTrainingDataForDeepLearning(
            parameters["input_path"],
            parameters["output_path"],
            image_chip_format=parameters.get("image_format", "TIFF"),
            tile_size_x=parameters["tile_size_x"],
            tile_size_y=parameters["tile_size_y"],
            stride_x=parameters["stride_x"],
            stride_y=parameters["stride_y"],
            metadata_format=parameters["metadata_format"],
        )
    return {"outputs": [parameters["output_path"]]}


BINDINGS = {
    "inspect.dataset": inspect_dataset,
    "vector.buffer": buffer_features,
    "vector.clip": clip_features,
    "vector.dissolve": dissolve_features,
    "vector.intersect": intersect_features,
    "vector.union": union_features,
    "vector.spatial_join": spatial_join,
    "vector.project": project_features,
    "vector.merge": merge_features,
    "vector.check_geometry": check_geometry,
    "vector.repair_geometry": repair_geometry,
    "raster.clip": clip_raster,
    "raster.project": project_raster,
    "raster.resample": resample_raster,
    "raster.extract_by_mask": extract_by_mask,
    "raster.slope": slope,
    "raster.zonal_statistics": zonal_statistics,
    "raster.mosaic": mosaic_rasters,
    "map.inspect_aprx": inspect_aprx,
    "map.export_layout": export_layout,
    "dl.detect_objects": detect_objects,
    "dl.classify_pixels": classify_pixels,
    "dl.classify_objects": classify_objects,
    "dl.detect_change": detect_change,
    "dl.translate_pixels": translate_pixels,
    "dl.export_training_data": export_training_data,
}
