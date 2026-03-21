import os
import json
from pathlib import Path
import shutil
from datetime import datetime
import yaml

class SampleExtractor:
    def __init__(self, source_folders, target_dir="samples"):
        self.source_folders = source_folders
        self.target_dir = Path(target_dir)
        
        # Read from config.yaml directly to avoid magic strings
        with open("config/config.yaml", 'r') as f:
            config = yaml.safe_load(f)
            
        self.paths = config.get('paths', {})
        
        self.pred_dir = self.target_dir / self.paths['predictions_dir']
        self.rev_dir = self.target_dir / self.paths['reviews_dir']
        self.img_dir = self.target_dir / self.paths['images_dir']
        
        for d in [self.pred_dir, self.rev_dir, self.img_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def extract(self):
        count = 0
        for folder in self.source_folders:
            folder_path = Path(folder)
            
            # Subdirectories for this source folder based on config
            source_rev_dir = folder_path / self.paths['reviews_dir']
            source_pred_dir = folder_path / self.paths['predictions_dir']
            source_img_dir = folder_path / self.paths['images_dir']
            
            if not source_rev_dir.exists():
                continue
                
            for review_file in source_rev_dir.glob("review_*.json"):
                with open(review_file, 'r') as f:
                    try:
                        data = json.load(f)
                    except:
                        continue
                        
                analysis = data.get('analysis', {})
                pred_content = data.get('prediction', {}).get('content', {})
                
                if not isinstance(analysis, dict): continue
                
                score = analysis.get('evaluation_score', 100)
                result = analysis.get('tp_sl_result', 'NEITHER')
                timestamp = pred_content.get('timestamp')
                symbol = pred_content.get('config_context', {}).get('symbol', 'BTCUSDT')
                
                if result == 'SL_HIT' or score <= 25:
                    source_pred_file = data.get('prediction', {}).get('source', '')
                    pred_path = source_pred_dir / source_pred_file
                    
                    if timestamp and pred_path.exists():
                        target_rev = self.rev_dir / review_file.name
                        target_pred = self.pred_dir / source_pred_file
                        
                        # Deduplication: Skip if prediction already exists in samples/
                        if target_pred.exists():
                            continue

                        try:
                            dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
                            for tf in ['15m', '1h']:
                                img_filename = f"{symbol}_{tf}_{dt.strftime('%Y%m%d_%H%M%S')}Z_chart.png"
                                source_img_path = source_img_dir / img_filename
                                target_img_path = self.img_dir / img_filename
                                
                                if source_img_path.exists() and source_img_path != target_img_path:
                                    shutil.copy(str(source_img_path), str(target_img_path))
                        except ValueError:
                            pass

                        if review_file != target_rev:
                            shutil.copy(str(review_file), str(target_rev))
                        if pred_path != target_pred:
                            shutil.copy(str(pred_path), str(target_pred))
                        count += 1

        print(f"Extraction complete. Moved {count} sample(s) to {self.target_dir}/")

if __name__ == "__main__":
    sources = ['data'] 
    extractor = SampleExtractor(sources)
    extractor.extract()
