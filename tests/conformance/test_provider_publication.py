"""ERP's capability-provider declaration against the pinned Shared catalogue, and the registration documents it would publish (ERP-CAP-07).

What this proves: the declaration is valid at the exact Shared commit contracts.lock.yaml pins, only IMPLEMENTED support ever reaches a
generated EngineRegistration (always DRAFT), and drift between a reviewed registration export and the declaration is detected. What it does
not prove: that anything is registered, certified, bound or healthy in the Control Plane; those are Control Plane and EA-09 authorities
(ADR-SHARED-017) and need runtime evidence, never this offline report."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

import _shared as shared

REPO = shared.REPO
_spec = importlib.util.spec_from_file_location("erp_provider_publication", REPO / "scripts/provider_publication.py")
publication = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publication)

DECLARATION = yaml.safe_load((REPO / ".baobab/capability-provider.yaml").read_text())
PROVIDER = "baobab-erp.idempiere"


def support_of(declaration, key):
    return next(s for s in declaration["providers"][0]["support"] if s["capability_key"] == key)


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = shared.ROOT
        cls.module, cls.commit = publication.load_shared(cls.checkout)

    def test_the_declaration_is_valid_at_the_pinned_commit(self):
        self.assertEqual(self.commit, shared.PIN)
        contracts, registrations, excluded = publication.prepare(self.module, self.checkout, DECLARATION)
        self.assertEqual([r["provider"]["provider_key"] for r in registrations], [PROVIDER])

    def test_only_implemented_support_is_ever_registered_and_always_as_draft(self):
        _, registrations, excluded = publication.prepare(self.module, self.checkout, DECLARATION)
        implemented = {s["capability_key"] for s in DECLARATION["providers"][0]["support"]
                       if s["implementation_status"] == "IMPLEMENTED"}
        registered = {s["capability_key"] for r in registrations for s in r["support"]}
        self.assertEqual(registered, implemented)
        self.assertTrue(all(r["provider"]["lifecycle"] == "DRAFT" for r in registrations))
        self.assertEqual({e["capability_key"] for e in excluded},
                         {s["capability_key"] for s in DECLARATION["providers"][0]["support"]} - implemented)
        self.assertTrue(all(e["implementation_status"] != "IMPLEMENTED" for e in excluded))

    def test_partial_support_is_not_published_merely_because_it_is_declared(self):
        order = "finance.order-consequence.process"
        self.assertEqual(support_of(DECLARATION, order)["implementation_status"], "PARTIAL")  # the honest state today
        _, registrations, excluded = publication.prepare(self.module, self.checkout, DECLARATION)
        self.assertNotIn(order, {s["capability_key"] for r in registrations for s in r["support"]})
        self.assertIn(order, {e["capability_key"] for e in excluded})

    def test_promoting_a_capability_to_implemented_is_what_publishes_it(self):
        order = "finance.order-consequence.process"
        promoted = copy.deepcopy(DECLARATION)
        support_of(promoted, order)["implementation_status"] = "IMPLEMENTED"
        _, registrations, excluded = publication.prepare(self.module, self.checkout, promoted)
        self.assertEqual({s["capability_key"] for r in registrations for s in r["support"]},
                         {order, "inventory.availability.query"})
        self.assertEqual(excluded, [])

    def test_a_declaration_with_no_implemented_support_is_not_registrable(self):
        none = copy.deepcopy(DECLARATION)
        for support in none["providers"][0]["support"]:
            support["implementation_status"] = "PARTIAL"
        _, registrations, excluded = publication.prepare(self.module, self.checkout, none)
        self.assertEqual(registrations, [])  # an empty list is not readiness
        self.assertEqual(len(excluded), len(none["providers"][0]["support"]))

    # -- drift against a reviewed registration export --------------------------------------------------------------------------------
    def generated(self):
        return publication.prepare(self.module, self.checkout, DECLARATION)[:2]

    def test_an_export_equal_to_the_declaration_has_no_drift(self):
        contracts, registrations = self.generated()
        self.assertEqual(publication.compare_exports(self.module, contracts, registrations, copy.deepcopy(registrations)), [])

    def test_missing_and_undeclared_registrations_are_drift(self):
        contracts, registrations = self.generated()
        self.assertEqual(publication.compare_exports(self.module, contracts, registrations, [])[0]["reason"], "MISSING_REGISTRATION")
        self.assertEqual(publication.compare_exports(self.module, contracts, [], registrations)[0]["reason"], "UNDECLARED_SUPPORT")

    def test_a_changed_or_substituted_registration_is_drift(self):
        contracts, registrations = self.generated()
        for mutate in (lambda e: e["provider"].update(engine_key="other-engine"),
                       lambda e: e["provider"].update(production_permitted=False),
                       lambda e: e["support"].append({"capability_key": "finance.order-consequence.process", "contract_versions": [1]})):
            exported = copy.deepcopy(registrations)
            mutate(exported[0])
            with self.subTest(mutate=mutate):
                self.assertEqual(publication.compare_exports(self.module, contracts, registrations, exported)[0]["reason"],
                                 "DECLARATION_MISMATCH")

    def test_a_live_lifecycle_is_not_a_registration_document(self):
        contracts, registrations = self.generated()
        exported = copy.deepcopy(registrations)
        exported[0]["provider"]["lifecycle"] = "ACTIVE"
        with self.assertRaises(ValueError):
            publication.compare_exports(self.module, contracts, registrations, exported)

    def test_duplicate_foreign_and_malformed_exports_are_denied(self):
        contracts, registrations = self.generated()
        foreign = copy.deepcopy(registrations)
        foreign[0]["repository"] = "baobab-iam"
        for exported in (registrations * 2, foreign, {}, [{}]):
            with self.subTest(exported=type(exported).__name__):
                with self.assertRaises(ValueError):
                    publication.compare_exports(self.module, contracts, registrations, exported)

    # -- construction is refused rather than guessed ------------------------------------------------------------------------------------
    def test_a_contract_version_or_evidence_path_that_does_not_exist_is_denied(self):
        for field, value in (("contract_versions", [999]), ("implementation_evidence", [{"type": "source", "path": "does/not/exist.py"}])):
            declaration = copy.deepcopy(DECLARATION)
            declaration["providers"][0]["support"][0][field] = value
            with self.subTest(field):
                with self.assertRaises(ValueError):
                    publication.prepare(self.module, self.checkout, declaration)

    def test_every_evidence_path_in_the_declaration_exists_in_this_repository(self):
        missing = [e["path"] for p in DECLARATION["providers"] for s in p["support"] for e in s["implementation_evidence"]
                   if not (REPO / e["path"]).exists()]
        self.assertEqual(missing, [])

    def test_a_checkout_at_another_commit_is_denied_before_its_code_is_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "contracts.lock.yaml").write_text(yaml.safe_dump(
                {"source": {"repository": "baobab-platform/shared", "commit": "0" * 40}}))
            with self.assertRaisesRegex(ValueError, "immutable ERP pin"):
                publication.load_shared(self.checkout, repository)

    def test_a_lock_naming_another_authority_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "contracts.lock.yaml").write_text(yaml.safe_dump(
                {"source": {"repository": "someone-else/shared", "commit": shared.PIN}}))
            with self.assertRaisesRegex(ValueError, "unapproved contract authority"):
                publication.load_shared(self.checkout, repository)


if __name__ == "__main__":
    unittest.main()


class SourceDirtinessTests(unittest.TestCase):
    def test_a_shared_checkout_nested_in_the_tree_is_not_erp_source_but_a_changed_file_is(self):
        import subprocess
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
            run("init", "-q")
            (repo / "tracked.txt").write_text("a")
            run("add", ".")
            run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
            nested = repo / ".shared-contracts"
            nested.mkdir()
            (nested / "file").write_text("shared")
            self.assertFalse(publication.source_dirty(nested, repo))
            (repo / "tracked.txt").write_text("changed")
            self.assertTrue(publication.source_dirty(nested, repo))
            self.assertTrue(publication.source_dirty(repo / "elsewhere", repo))
