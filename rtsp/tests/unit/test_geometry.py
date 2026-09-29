import numpy as np
import pytest

from piv.geometry import normalize_aoi_corners, sanitize_dist_coeffs


def test_axis_aligned_rectangle_scrambled_order_returns_TL_TR_BR_BL():
    scrambled = [[100, 200], [10, 20], [100, 20], [10, 200]]
    result = normalize_aoi_corners(scrambled)
    assert result == [[10.0, 20.0], [100.0, 20.0], [100.0, 200.0], [10.0, 200.0]]


def test_axis_aligned_rectangle_already_ordered_is_unchanged():
    rect = [[10, 20], [100, 20], [100, 200], [10, 200]]
    result = normalize_aoi_corners(rect)
    assert result == [[10.0, 20.0], [100.0, 20.0], [100.0, 200.0], [10.0, 200.0]]


def test_axis_aligned_rectangle_reverse_order_normalizes_same_way():
    rect = [[10, 200], [100, 200], [100, 20], [10, 20]]
    result = normalize_aoi_corners(rect)
    assert result == [[10.0, 20.0], [100.0, 20.0], [100.0, 200.0], [10.0, 200.0]]


def test_axis_aligned_rectangle_starting_from_BR_normalizes_same_way():
    rect = [[100, 200], [100, 20], [10, 20], [10, 200]]
    result = normalize_aoi_corners(rect)
    assert result == [[10.0, 20.0], [100.0, 20.0], [100.0, 200.0], [10.0, 200.0]]


def test_slightly_rotated_quadrilateral_scrambled_order_normalizes_deterministically():
    rotated_tl_tr_br_bl = [
        [26.31198710447437, 13.55313423388941],
        [114.94468487557309, 29.181470223913152],
        [83.68801289552563, 206.4468657661106],
        [-4.944684875573088, 190.81852977608685],
    ]
    assert normalize_aoi_corners(rotated_tl_tr_br_bl) == rotated_tl_tr_br_bl

    scrambled = [
        rotated_tl_tr_br_bl[2],
        rotated_tl_tr_br_bl[1],
        rotated_tl_tr_br_bl[3],
        rotated_tl_tr_br_bl[0],
    ]
    result = normalize_aoi_corners(scrambled)
    assert result == rotated_tl_tr_br_bl


def test_rotated_diamond_quadrilateral_normalizes_regardless_of_input_order():
    diamond_top_right_bottom_left = [[50, 10], [90, 50], [50, 90], [10, 50]]
    assert normalize_aoi_corners(diamond_top_right_bottom_left) == [
        [50.0, 10.0], [90.0, 50.0], [50.0, 90.0], [10.0, 50.0],
    ]

    scrambled = [[90, 50], [10, 50], [50, 90], [50, 10]]
    result = normalize_aoi_corners(scrambled)
    assert result == [[50.0, 10.0], [90.0, 50.0], [50.0, 90.0], [10.0, 50.0]]


def test_wrong_shape_raises_runtime_error():
    with pytest.raises(RuntimeError):
        normalize_aoi_corners([[1, 2], [3, 4], [5, 6]])


def test_wrong_shape_five_points_raises_runtime_error():
    with pytest.raises(RuntimeError):
        normalize_aoi_corners([[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]])


def test_output_is_plain_python_list_of_lists_of_floats():
    scrambled = [[100, 200], [10, 20], [100, 20], [10, 200]]
    result = normalize_aoi_corners(scrambled)
    assert isinstance(result, list)
    assert all(isinstance(pt, list) and len(pt) == 2 for pt in result)
    assert all(isinstance(v, float) for pt in result for v in pt)


def test_none_input_gives_five_zero_rows():
    assert sanitize_dist_coeffs(None) == [[0.0], [0.0], [0.0], [0.0], [0.0]]


def test_short_list_is_zero_padded_to_five():
    assert sanitize_dist_coeffs([1.0, 2.0]) == [[1.0], [2.0], [0.0], [0.0], [0.0]]


def test_empty_list_is_zero_padded_to_five():
    assert sanitize_dist_coeffs([]) == [[0.0], [0.0], [0.0], [0.0], [0.0]]


def test_long_list_is_truncated_to_first_five():
    assert sanitize_dist_coeffs(list(range(8))) == [
        [0.0], [1.0], [2.0], [3.0], [4.0],
    ]


def test_exact_five_list_is_passed_through():
    assert sanitize_dist_coeffs([1, 2, 3, 4, 5]) == [
        [1.0], [2.0], [3.0], [4.0], [5.0],
    ]


def test_nested_list_5x1_is_flattened_and_passed_through():
    nested = [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert sanitize_dist_coeffs(nested) == [[1.0], [2.0], [3.0], [4.0], [5.0]]


def test_nested_list_short_is_flattened_then_zero_padded():
    nested = [[1.0], [2.0]]
    assert sanitize_dist_coeffs(nested) == [[1.0], [2.0], [0.0], [0.0], [0.0]]


def test_numpy_1d_array_short_is_zero_padded():
    arr = np.array([1.0, 2.0, 3.0])
    assert sanitize_dist_coeffs(arr) == [[1.0], [2.0], [3.0], [0.0], [0.0]]


def test_numpy_column_array_long_is_flattened_then_truncated():
    arr = np.array([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]])
    assert sanitize_dist_coeffs(arr) == [[1.0], [2.0], [3.0], [4.0], [5.0]]


def test_numpy_array_exact_five_is_passed_through():
    arr = np.array([0.1, -0.05, 0.002, 0.0, -0.0007])
    result = sanitize_dist_coeffs(arr)
    assert result == [[0.1], [-0.05], [0.002], [0.0], [-0.0007]]


def test_all_values_are_python_floats_not_numpy_scalars():
    result = sanitize_dist_coeffs(np.array([1, 2, 3, 4, 5]))
    for row in result:
        assert isinstance(row[0], float)
