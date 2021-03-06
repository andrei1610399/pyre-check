from typing import Any, Dict, List
from unittest import TestCase

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from ..db import DB, DBType
from ..models import (
    Run,
    RunStatus,
    SharedText,
    SharedTextKind,
    TraceFrameLeafAssoc,
    create as create_models,
)
from ..trace_operator import TraceOperator
from .fake_object_generator import FakeObjectGenerator


class TraceOperatorTest(TestCase):
    def setUp(self) -> None:
        self.db = DB(DBType.MEMORY)
        create_models(self.db)
        self.fakes = FakeObjectGenerator()

    def _basic_trace_frames(self) -> List[Any]:
        return [
            self.fakes.precondition(
                caller="call1",
                caller_port="root",
                callee="call2",
                callee_port="param0",
                location=(1, 1, 1),
            ),
            self.fakes.precondition(
                caller="call2",
                caller_port="param0",
                callee="leaf",
                callee_port="sink",
                location=(1, 2, 1),
            ),
        ]

    def _all_leaves_by_kind(
        self, session: Session, kind: SharedTextKind
    ) -> Dict[int, str]:
        return {
            int(id): contents
            for id, contents in session.query(
                SharedText.id, SharedText.contents
            ).filter(SharedText.kind == kind)
        }

    def testNextTraceFrames(self) -> None:
        run = self.fakes.run()
        frames = self._basic_trace_frames()
        sink = self.fakes.sink("sink1")
        self.fakes.saver.add(
            TraceFrameLeafAssoc.Record(
                trace_frame_id=frames[1].id, leaf_id=sink.id, trace_length=1
            )
        )
        self.fakes.save_all(self.db)

        with self.db.make_session() as session:
            session.add(run)
            session.commit()
            leaf_dicts = (
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SOURCE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SOURCE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SINK,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SINK)[[Named(cls, SharedTextKind)], typing.Any]`.Pyre
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.FEATURE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.FEATURE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
            )

            latest_run_id = (
                session.query(func.max(Run.id))
                .filter(Run.status == RunStatus.FINISHED)
                .scalar()
            )

            next_frames = TraceOperator.next_forward_trace_frames(
                leaf_dicts, session, latest_run_id, set(), {"sink1"}, frames[0], set()
            )
            self.assertEqual(len(next_frames), 1)
            self.assertEqual(int(next_frames[0].id), int(frames[1].id))

    def testNextTraceFramesMultipleRuns(self) -> None:
        run1 = self.fakes.run()
        frames = self._basic_trace_frames()
        self.fakes.save_all(self.db)

        run2 = self.fakes.run()
        frames.extend(self._basic_trace_frames())

        sink = self.fakes.sink("sink1")
        self.fakes.saver.add_all(
            [
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[1].id, leaf_id=sink.id, trace_length=0
                ),
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[3].id, leaf_id=sink.id, trace_length=0
                ),
            ]
        )
        self.fakes.save_all(self.db)

        with self.db.make_session() as session:
            session.add(run1)
            session.add(run2)
            session.commit()

            leaf_dicts = (
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SOURCE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SOURCE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SINK,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SINK)[[Named(cls, SharedTextKind)], typing.Any]`.Pyre
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.FEATURE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.FEATURE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
            )

            latest_run_id = (
                session.query(func.max(Run.id))
                .filter(Run.status == RunStatus.FINISHED)
                .scalar()
            )

            next_frames = TraceOperator.next_forward_trace_frames(
                leaf_dicts, session, latest_run_id, set(), {"sink1"}, frames[2], set()
            )
            self.assertEqual(len(next_frames), 1)
            self.assertEqual(int(next_frames[0].id), int(frames[3].id))

    def testNavigateTraceFrames(self) -> None:
        run = self.fakes.run()
        frames = self._basic_trace_frames()
        sink = self.fakes.sink("sink1")
        self.fakes.saver.add(
            TraceFrameLeafAssoc.Record(
                trace_frame_id=frames[1].id, leaf_id=sink.id, trace_length=1
            )
        )
        self.fakes.save_all(self.db)
        with self.db.make_session() as session:
            session.add(run)
            session.commit()

            leaf_dicts = (
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SOURCE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SOURCE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SINK,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SINK)[[Named(cls, SharedTextKind)], typing.Any]`.Pyre
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.FEATURE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.FEATURE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
            )

            latest_run_id = (
                session.query(func.max(Run.id))
                .filter(Run.status == RunStatus.FINISHED)
                .scalar()
            )

            result = TraceOperator.navigate_trace_frames(
                leaf_dicts, session, latest_run_id, set(), {"sink1"}, [frames[0]]
            )
            self.assertEqual(len(result), 2)
            self.assertEqual(int(result[0][0].id), int(frames[0].id))
            self.assertEqual(int(result[1][0].id), int(frames[1].id))

    def testNavigateTraceFramesDetectsCycle(self) -> None:
        """This test checks that we don't get stuck in a cycle. Without cycle
        detection code, this test will go from 1->2->1->2->... . With cycle
        detection code it goes 1->2->3->4.
        """
        run = self.fakes.run()
        frames = [
            self.fakes.precondition(
                caller="call1",
                caller_port="param1",
                callee="call2",
                callee_port="param2",
            ),
            self.fakes.precondition(
                caller="call2",
                caller_port="param2",
                callee="call1",
                callee_port="param1",
            ),
            self.fakes.precondition(
                caller="call1",
                caller_port="param1",
                callee="call3",
                callee_port="param3",
            ),
            self.fakes.precondition(
                caller="call3", caller_port="param3", callee="leaf", callee_port="sink"
            ),
        ]
        sink = self.fakes.sink("sink")
        self.fakes.saver.add_all(
            [
                # This trace_length 0 is part of a bug.
                # See models.py:TraceFrameLeafAssoc.trace_length
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[0].id, leaf_id=sink.id, trace_length=0
                ),
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[1].id, leaf_id=sink.id, trace_length=1
                ),
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[2].id, leaf_id=sink.id, trace_length=1
                ),
                TraceFrameLeafAssoc.Record(
                    trace_frame_id=frames[3].id, leaf_id=sink.id, trace_length=0
                ),
            ]
        )

        self.fakes.save_all(self.db)

        with self.db.make_session() as session:
            session.add(run)
            session.commit()

            leaf_dicts = (
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SOURCE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SOURCE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.SINK,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.SINK)[[Named(cls, SharedTextKind)], typing.Any]`.Pyre
                ),
                self._all_leaves_by_kind(
                    session,
                    SharedTextKind.FEATURE,  # pyre-fixme[6] Expected `SharedTextKind` but got `typing.Callable(SharedTextKind.FEATURE)[[Named(cls, SharedTextKind)], typing.Any]`.
                ),
            )

            latest_run_id = (
                session.query(func.max(Run.id))
                .filter(Run.status == RunStatus.FINISHED)
                .scalar()
            )

            result = TraceOperator.navigate_trace_frames(
                leaf_dicts, session, latest_run_id, set(), {"sink"}, [frames[0]]
            )
            self.assertEqual(len(frames), 4)
            self.assertEqual(
                [int(frame.id) for frame, _branches in result],
                [int(frame.id) for frame in frames],
            )
