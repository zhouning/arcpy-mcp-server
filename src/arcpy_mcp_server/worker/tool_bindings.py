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
}
