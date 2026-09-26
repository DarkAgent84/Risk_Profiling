"""
Pipeline module bridge. Exports modular components from src/.
"""
from src.config import *
from src.ingestion import normalize_column_name, load_datasets as load_and_validate_data, find_raw_files as find_default_files
from src.behavior import extract_behavioral_features as build_behavior_features
from src.scoring import compute_risk_profile as build_risk_profile
from src.evaluation import print_portfolio_summary as print_summary
from main import run_pipeline

if __name__ == '__main__':
    from main import main
    main()
