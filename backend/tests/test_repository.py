import unittest
from uuid import uuid4

from backend.app.domain import Inspection, InvalidDomainData, PropertyDetails, Room, TransitionConflict
from backend.app.repository import InMemoryInspectionRepository, NotFound


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryInspectionRepository()
        self.inspection = Inspection(PropertyDetails("Example address"), "Example renter")
        self.repo.create(self.inspection)

    def test_create_get_and_isolation(self):
        self.assertEqual(self.repo.get(self.inspection.id).inspection, self.inspection)
        with self.assertRaises(NotFound):
            InMemoryInspectionRepository().get(self.inspection.id)
        with self.assertRaises(NotFound):
            self.repo.get(uuid4())
        with self.assertRaises(InvalidDomainData):
            self.repo.get([])
        with self.assertRaises(TransitionConflict):
            self.repo.create(self.inspection)

    def test_copy_on_create_read_and_update(self):
        # Deliberate mutation here tests the copy boundary, not domain setters.
        object.__setattr__(self.inspection, "renter_name", "Changed outside")
        self.assertEqual(self.repo.get(self.inspection.id).inspection.renter_name, "Example renter")
        retained = []
        def add(state):
            room = Room(state.inspection, "Room")
            state.rooms[room.id] = room
            retained.append(state)
        returned = self.repo.update(self.inspection.id, add)
        retained[0].rooms.clear()
        returned.rooms.clear()
        self.assertEqual(len(self.repo.get(self.inspection.id).rooms), 1)

    def test_exception_rolls_back_entire_update(self):
        def fail(state):
            room = Room(state.inspection, "Room")
            state.rooms[room.id] = room
            raise InvalidDomainData("abort")
        with self.assertRaises(InvalidDomainData):
            self.repo.update(self.inspection.id, fail)
        self.assertEqual(self.repo.get(self.inspection.id).rooms, {})

    def test_unregistered_parent_is_rejected(self):
        def invalid(state):
            room = Room(self.inspection, "Detached parent")
            state.rooms[room.id] = room
        with self.assertRaises(InvalidDomainData):
            self.repo.update(self.inspection.id, invalid)
        self.assertEqual(self.repo.get(self.inspection.id).rooms, {})


    def test_list_inspections_returns_detached_summaries(self):
        listed = self.repo.list_inspections()
        self.assertEqual([i.id for i in listed], [self.inspection.id])
        self.assertIsNot(listed[0], self.inspection)
        self.assertIsNot(listed[0], self.repo.list_inspections()[0])
        listed.clear()
        self.assertEqual(len(self.repo.list_inspections()), 1)
        self.assertEqual(InMemoryInspectionRepository().list_inspections(), [])
