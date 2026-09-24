import unittest
from knight_flow.web_shell.menu_geometry import feature_bounds


class MenuGeometryTests(unittest.TestCase):
    def test_opening_right_keeps_the_original_menu_in_place(self):
        self.assertEqual(feature_bounds([40,40,380,600],[0,0,1600,1000],True),([40,40,760,600],'right'))

    def test_opening_left_does_not_cross_the_monitor_edge(self):
        self.assertEqual(feature_bounds([810,40,380,600],[0,0,1200,1000],True),([430,40,760,600],'left'))

    def test_narrow_monitor_keeps_one_readable_column(self):
        self.assertEqual(feature_bounds([8,40,380,500],[0,0,500,700],True),([8,40,380,500],'replace'))

    def test_closing_restores_the_exact_position(self):
        self.assertEqual(feature_bounds([-800,40,380,600],[-1200,0,0,1000],False),([-800,40,380,600],'right'))


if __name__=='__main__':unittest.main()
