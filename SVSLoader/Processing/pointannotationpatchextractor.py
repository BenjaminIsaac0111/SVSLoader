import os
from pathlib import Path
import cv2 as cv
import numpy as np
from PIL import Image
from bs4 import BeautifulSoup as soup
from SVSLoader.Processing.patchextractor import PatchExtractor


class PointAnnotationPatchExtractor(PatchExtractor):
    """
    PointAnnotationPatchExtractor is a concrete class that extends PatchExtractor and provides functionality
    for extracting patches based on point annotations.

    Attributes:
        errors (int): Number of errors encountered during patch extraction.
        patch_center (tuple): Center coordinates of the patch.
        ground_truth_mask (None or ndarray): Ground truth mask for the patch.

    Methods:
        __init__(self, configuration=None):
            Initializes the PointAnnotationPatchExtractor object.
            Args:
                configuration (str or dict or pathlib.PurePath): Configuration for PointAnnotationPatchExtractor.
                    It can be a path to a configuration file, a dictionary containing configuration,
                    or a pathlib.PurePath object representing a configuration file path.

        get_patch_center(self):
            Calculates and returns the center coordinates of the patch.

        extract_institute_id(self):
            Extracts the institute ID from the WSI filename.

        read_patch_region(self, level=0, loc_idx=None):
            Reads the region of the patch specified by the location index.

        build_patch(self):
            Builds the patch by concatenating the loaded region and the ground truth mask.

        parse_annotation(self):
            Parses the point annotations and extracts the points coordinates and patch classes.

        build_patch_filenames(self):
            Builds the filenames for each patch.

        build_ground_truth_mask(self):
            Builds the ground truth mask for the current patch.

        save_patch(self):
            Saves the current patch.

        run_extraction(self, dry=False):
            Runs the patch extraction process.

    """

    def __init__(self, configuration=None):
        """
        Initializes the PointAnnotationPatchExtractor object.

        Args:
            configuration (str or dict or pathlib.PurePath): Configuration for PointAnnotationPatchExtractor.
                It can be a path to a configuration file, a dictionary containing configuration,
                or a pathlib.PurePath object representing a configuration file path.
        """
        super().__init__(configuration=configuration)
        self.errors = 0
        self.patch_center = self.get_patch_center()
        self.ground_truth_mask = None

    def get_patch_center(self):
        """
        Calculates and returns the center coordinates of the patch.

        Returns:
            tuple: Center coordinates of the patch.
        """
        patch_center_x, patch_center_y = self.patch_w_h_scaled
        return int(round(patch_center_x / 2)), int(round(patch_center_y / 2))

    def extract_institute_id(self):
        """
        Extracts the institute ID from the WSI filename.
        """
        self.batch_id = Path(self.find_svs_path_by_id(pattern=self.whole_silde_image_id)).parts[-2]

    def read_patch_region(self, level=0, loc_idx=None):
        """
        Reads the region of the patch specified by the location index.

        Args:
            level (int): Level of the WSI to read the patch region from.
            loc_idx (int): Index of the location (patch) to be read.
        """
        self.point_index = loc_idx
        self.loaded_wsi_region = self.loaded_svs.read_region(
            location=self.patch_coordinates[self.point_index],
            level=level,
            size=self.patch_w_h_scaled,
            padding=True
        )
        self.loaded_wsi_region = np.array(self.loaded_wsi_region.convert("RGB"))
        self.loaded_wsi_region = cv.resize(
            src=self.loaded_wsi_region,
            dsize=self.patch_w_h
        )
        self.selected_patch_class = self.patch_classes[self.point_index]

    def build_patch(self):
        """
        Builds the patch by concatenating the loaded region and the ground truth mask.
        """
        self.patch = cv.hconcat([self.loaded_wsi_region, self.ground_truth_mask])

    def parse_annotation(self):
        """
        Parses the point annotations and extracts the points coordinates and patch classes.
        """
        points_coor = []
        patch_classes = []
        for associated_file in self.loaded_associated_files:
            annotation = soup(''.join(associated_file.readlines()), 'html.parser')
            points = annotation.findAll('region', {'type': '3'})
            for i, point in enumerate(points):
                if point['text'].isdigit():
                    patch_classes.append(point['text'])
                    points_coor.append((round(float(point.find('vertices').contents[0]['x'])),
                                        round(float(point.find('vertices').contents[0]['y']))))
        self.points_coordinates = points_coor
        self.patch_classes = patch_classes
        self.patch_coordinates = [(int(coor[0] - (self.patch_w_h_scaled[0] / 2)),
                                   int(coor[1] - (self.patch_w_h_scaled[1] / 2))) for coor in
                                  self.points_coordinates]

    def build_patch_filenames(self):
        """
        Builds the filenames for each patch.
        """
        self.patch_filenames = []
        _filenames = []
        for i, loc in enumerate(self.patch_coordinates):
            _patch_filename = ''
            if self.batch_id:
                _patch_filename += f'{self.batch_id[-2:]}_'
            _patch_filename += f'{self.whole_silde_image_id[:-4]}_{str(i)}_Class_{self.patch_classes[i]}.png'
            _filenames.append(_patch_filename)
            self.patch_filenames = _filenames

    def build_ground_truth_mask(self):
        """
        Builds the ground truth mask for the current patch.
        """
        circle_center_coor = tuple(int(coor / 2) for coor in self.patch_w_h)
        mask = np.zeros(self.loaded_wsi_region.shape, dtype=np.uint8)
        patch_class = int(self.patch_classes[self.point_index]) + 1
        self.ground_truth_mask = cv.circle(img=mask, center=circle_center_coor,
                                           radius=self.CONFIG['CONTEXT_MASK_RADIUS'], color=(0, 0, patch_class),
                                           thickness=-1)

    def save_patch(self):
        """
        Saves the current patch.
        """
        patch_filepath = f'{self.CONFIG["PATCHES_DIR"]}\\{self.patch_filenames[self.point_index]}'
        Image.fromarray(self.patch).save(fp=patch_filepath)

    def run_extraction(self, dry=False):
        """
        Runs the patch extraction process.

        Args:
            dry (bool): If True, performs a dry run without saving patches.
        """
        if not os.path.exists(f'{self.CONFIG["PATCHES_DIR"]}'):
            os.mkdir(f'{self.CONFIG["PATCHES_DIR"]}')
        _existing = [file for file in os.listdir(self.CONFIG['PATCHES_DIR']) if file.endswith('.png')]
        for i, file in enumerate(self.whole_slide_image_filenames):
            self.load_svs_by_id(file)
            self.load_associated_files()
            self.parse_annotation()
            self.build_patch_filenames()
            self.errors = 0
            for j, filename in enumerate(self.patch_filenames):
                if filename not in _existing:
                    self.read_patch_region(loc_idx=j)
                    if not dry:
                        try:
                            self.build_ground_truth_mask()
                        except ValueError:
                            self.errors += 1
                        self.build_patch()
                        self.save_patch()

            self.loader_message += f'\tExtracted {len(self.patch_filenames) - self.errors} patches.'
            self.loader_message += f'\tErrors {self.errors}\n'
            self.print_loader_message()
