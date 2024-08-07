from sodapy import Socrata
import requests
from requests.auth import HTTPBasicAuth
import json
import argparse
import sys
import os

# Create a parser and add arguments
parser = argparse.ArgumentParser(description='311 Requests Data')
parser.add_argument('--page_size', type=int, help='how many rows to get per page', required=True)
parser.add_argument('--num_pages', type=int, help='how many pages to get in total', required=True)
parser.add_argument('--start_page', type=int, help='page number to start from', default=0)
args = parser.parse_args(sys.argv[1:])

# Environment variables
DATASET_ID = os.environ["DATASET_ID"]
APP_TOKEN = os.environ["APP_TOKEN"]
ES_HOST = os.environ["ES_HOST"]
ES_USERNAME = os.environ["ES_USERNAME"]
ES_PASSWORD = os.environ["ES_PASSWORD"]
INDEX_NAME = os.environ["INDEX_NAME"]

def create_index():
    try:
        resp = requests.put(
            f"{ES_HOST}/{INDEX_NAME}",
            auth=HTTPBasicAuth(ES_USERNAME, ES_PASSWORD),
            json={
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 1
                },
                "mappings": {
                    "properties": {
                        "starfire_incident_id": {"type": "float"},
                        "incident_datetime": {"type": "date"},
                        "incident_classification": {"type": "keyword"},
                        "incident_borough": {"type": "keyword"},
                        "incident_response_seconds_qy": {"type": "float"}, 
                    }
                },
            }
        )
        resp.raise_for_status()
        print("Index created or already exists.")
    except Exception as e:
        print("Index already exists! Skipping")

def fetch_data(client, offset, page_size):
    return client.get(DATASET_ID, limit=page_size, offset=offset, where="incident_datetime IS NOT NULL AND starfire_incident_id IS NOT NULL")

def transform_data(rows):
    es_rows = []
    for row in rows:
        try:
            es_row = {
                "starfire_incident_id": row["starfire_incident_id"],
                "incident_datetime": row["incident_datetime"],
                "incident_classification": row["incident_classification"],
                "incident_borough": row["incident_borough"],
                "incident_response_seconds_qy": float(row["incident_response_seconds_qy"])
            }
            es_rows.append(es_row)
        except Exception as e:
            print(f"Error: {e}, skipping row: {row}")
            continue
    return es_rows

def bulk_upload(es_rows):
    bulk_upload_data = ""
    for line in es_rows:
        action = '{"index": {"_index": "' + INDEX_NAME + '", "_id": "' + str(line["starfire_incident_id"]) + '"}}'
        data = json.dumps(line)
        bulk_upload_data += f"{action}\n{data}\n"
    
    try:
        resp = requests.post(
            f"{ES_HOST}/_bulk",
            data=bulk_upload_data,
            auth=HTTPBasicAuth(ES_USERNAME, ES_PASSWORD),
            headers={"Content-Type": "application/x-ndjson"}
        )
        resp.raise_for_status()
        print("Data uploaded successfully.")
    except Exception as e:
        print(f"Failed to insert in ES: {e}")

if __name__ == '__main__':
    create_index()
    
    client = Socrata("data.cityofnewyork.us", APP_TOKEN, timeout=10000)

    for page in range(args.start_page, args.num_pages):
        offset = page * args.page_size
        rows = fetch_data(client, offset, args.page_size)
        es_rows = transform_data(rows)
        bulk_upload(es_rows)
