import unittest
from unittest.mock import Mock, patch

from emergency_control import EmergencyController, EmergencyStopped


class EmergencyControllerTests(unittest.TestCase):
    def test_latched_stop_blocks_future_work(self):
        controller = EmergencyController()
        controller.check()
        controller.stop()
        self.assertTrue(controller.stopped)
        with self.assertRaises(EmergencyStopped):
            controller.check()
        controller.stop()
        with self.assertRaises(EmergencyStopped):
            controller.register(Mock())

    def test_registered_child_is_killed(self):
        controller = EmergencyController()
        child = Mock()
        child.poll.return_value = None
        child.pid = 12345
        controller.register(child)
        with patch("emergency_control.os.name", "posix"):
            controller.stop()
        child.kill.assert_called_once()

    def test_finished_child_is_not_killed(self):
        controller = EmergencyController()
        child = Mock()
        child.poll.side_effect = [None, 0]
        controller.register(child)
        with patch("emergency_control.os.name", "posix"):
            controller.stop()
        child.kill.assert_not_called()

    def test_unregistered_child_is_not_killed(self):
        controller = EmergencyController()
        child = Mock()
        child.poll.return_value = None
        controller.register(child)
        controller.unregister(child)
        with patch("emergency_control.os.name", "posix"):
            controller.stop()
        child.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
