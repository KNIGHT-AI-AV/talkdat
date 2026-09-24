from __future__ import annotations

import unittest

from knight_flow.model_catalog import LOCAL_MODEL_CATALOG
from knight_flow.pc_audit import PcAudit, audit_pc, cloud_is_the_kind_default, recommended_local_model


class PcAuditTests(unittest.TestCase):
    """X-59.C-2: the install-time scan and its conservative tier mapping."""

    def test_the_real_machine_audits_without_raising(self) -> None:
        audit = audit_pc()
        self.assertGreaterEqual(audit.logical_cores, 1)
        self.assertGreater(audit.ram_gb, 0.5, "RAM readback failed")
        self.assertIn("cores", audit.summary)

    def test_every_recommendation_is_a_real_catalog_model(self) -> None:
        catalog_ids = {entry.id for entry in LOCAL_MODEL_CATALOG}
        shapes = [
            PcAudit(4, 4.0, False), PcAudit(4, 8.0, False),
            PcAudit(8, 16.0, False), PcAudit(12, 32.0, False),
            PcAudit(16, 32.0, True), PcAudit(2, 3.5, False),
        ]
        for shape in shapes:
            model = recommended_local_model(shape)
            self.assertIn(model, catalog_ids, f"{shape}: {model} not in catalog")

    def test_the_founder_machine_shape_gets_the_packaged_default(self) -> None:
        # i7-8700, 32 GB, no CUDA -- the machine the soak actually ran on.
        self.assertEqual(recommended_local_model(PcAudit(12, 32.0, False)),
                         "parakeet-tdt-0.6b-v3")

    def test_a_weak_machine_is_told_the_truth(self) -> None:
        weak = PcAudit(2, 3.5, False)
        self.assertTrue(cloud_is_the_kind_default(weak))
        self.assertEqual(recommended_local_model(weak), "whisper-base.en")

    def test_a_gpu_box_gets_the_big_model(self) -> None:
        self.assertEqual(recommended_local_model(PcAudit(16, 32.0, True)),
                         "whisper-large-v3-turbo")


if __name__ == "__main__":
    unittest.main()
