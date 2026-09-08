"""
lambda/tests/test_lambdas.py

Unit test dasar untuk kedua Lambda AgroSense dengan mock boto3
(validasi format ID, parsing body, hitung risk/forecast tanpa AWS asli).

Jalankan:  python -m unittest discover -s lambda/tests
"""
import json
import os
import sys
import unittest
from importlib import util
from unittest import mock

# boto3 client dibuat saat import module; pastikan region tersedia di test.
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

_LAMBDA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # lambda/


def _load(name: str, path: str):
    spec = util.spec_from_file_location(name, path)
    module = util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


risk_fn = _load("risk_lambda",
                os.path.join(_LAMBDA_ROOT, "lambda_recommendation", "lambda_function.py"))
yield_fn = _load("yield_lambda",
                 os.path.join(_LAMBDA_ROOT, "lambda_forecasting", "lambda_function.py"))


class TestRiskPrediction(unittest.TestCase):
    def test_validate_farm_id_ok(self):
        self.assertEqual(risk_fn.validate_farm_id(" F00001 "), "F00001")

    def test_validate_farm_id_invalid(self):
        with self.assertRaises(ValueError):
            risk_fn.validate_farm_id("X123")

    def test_validate_crop_id_invalid(self):
        with self.assertRaises(ValueError):
            risk_fn.validate_crop_id("abc")

    def test_flatten_features(self):
        farm = {"farm_size_hectare": "10", "total_activities": 5, "crop_diversity": 2}
        crop = {"avg_yield_ton_per_ha": 4.5}
        vec = risk_fn._flatten_features(farm, crop)
        # farm_size_hectare, total_activities, total_volume(0), avg_volume(0),
        # crop_diversity(2), region_avg_quantity(0), yield(4.5)
        self.assertEqual(vec, [10.0, 5.0, 0.0, 0.0, 2.0, 0.0, 4.5])

    def test_compute_risk_percentage_clipped(self):
        class FakeModel:
            def predict_proba(self, x):
                return [[0.1, 0.95]]
        risk = risk_fn.compute_risk_percentage(FakeModel(), {}, {})
        self.assertAlmostEqual(risk, 95.0)

    @mock.patch.object(risk_fn, "cloudwatch")
    def test_emit_high_risk_metric(self, mock_cw):
        risk_fn.emit_high_risk_metric()
        mock_cw.put_metric_data.assert_called_once()
        call = mock_cw.put_metric_data.call_args
        self.assertEqual(call.kwargs["Namespace"], "AgroSense/Business")
        self.assertEqual(call.kwargs["MetricData"][0]["MetricName"], "HighRiskFarmCount")

    @mock.patch.object(risk_fn, "get_farm_features")
    @mock.patch.object(risk_fn, "get_crop_features")
    @mock.patch.object(risk_fn, "load_model")
    @mock.patch.object(risk_fn, "emit_high_risk_metric")
    def test_handler_ok_low_risk(self, mock_cw, mock_load, mock_crop, mock_farm):
        mock_farm.return_value = {"farm_id": "F00001"}
        mock_crop.return_value = {"crop_id": "C00001"}

        class FakeModel:
            def predict_proba(self, x):
                return [[0.9, 0.1]]

        mock_load.return_value = FakeModel()
        result = risk_fn.lambda_handler(
            {"body": json.dumps({"farm_id": "F00001", "crop_id": "C00001"})}, mock.Mock()
        )
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["risk_percentage"], 10.0)
        mock_cw.assert_not_called()

    @mock.patch.object(risk_fn, "get_farm_features", return_value=None)
    @mock.patch.object(risk_fn, "get_crop_features", return_value={"crop_id": "C00001"})
    def test_handler_farm_not_found(self, _mock_crop, _mock_farm):
        result = risk_fn.lambda_handler(
            {"body": json.dumps({"farm_id": "F00001", "crop_id": "C00001"})}, mock.Mock()
        )
        self.assertEqual(result["statusCode"], 404)
        self.assertIn("tidak ditemukan", json.loads(result["body"])["message"])

    def test_handler_bad_body(self):
        result = risk_fn.lambda_handler({"body": "{bad json"}, mock.Mock())
        self.assertEqual(result["statusCode"], 400)


class TestYieldForecasting(unittest.TestCase):
    def test_run_forecast_row_shape(self):
        yf_rows = yield_fn.run_forecast(model=None, crop_id="C00001")
        self.assertEqual(len(yf_rows), yield_fn.FORECAST_PERIODS)
        first = yf_rows[0]
        self.assertEqual(set(first.keys()),
                         {"crop_id", "forecast_period", "forecast_quantity_ton", "generated_at"})
        self.assertGreater(first["forecast_quantity_ton"], 0)
        self.assertIn("T", first["generated_at"])  # ISO8601 timestamp

    @mock.patch.object(yield_fn.dynamodb, "Table")
    def test_write_yield_history_uses_batch(self, mock_table):
        os.environ["YIELD_HISTORY_TABLE"] = "agrosense-yield-history"
        yield_fn.YIELD_HISTORY_TABLE = os.environ.get("YIELD_HISTORY_TABLE")
        mock_batch = mock.MagicMock()
        mock_table.return_value.batch_writer.return_value.__enter__.return_value = mock_batch
        yield_fn.write_yield_history([{"crop_id": "C1"}])
        mock_batch.put_item.assert_called_once()

    @mock.patch.object(yield_fn, "list_crop_ids", return_value=["C00001", "C00002"])
    @mock.patch.object(yield_fn, "write_yield_history")
    @mock.patch.object(yield_fn, "load_model", return_value=None)
    def test_handler_writes_and_returns_summary(self, _m, _w, _l):
        summary = yield_fn.lambda_handler({}, mock.Mock(aws_request_id="test-run-1"))
        self.assertEqual(summary["run_id"], "test-run-1")
        self.assertEqual(summary["crops_processed"], 2)
        self.assertEqual(summary["forecast_items_written"], yield_fn.FORECAST_PERIODS * 2)


if __name__ == "__main__":
    unittest.main()