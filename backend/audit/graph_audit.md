# Knowledge Graph Audit Report

- Graph: `vector_db_qdrant\knowledge_graph.json`
- Scraped docs: `backend\data\srm_docs`

## Summary

- **§ 1_isolated_admissions** — 5 row(s)
- **§ 2_unlinked_programs** — 140 row(s)
- **§ 3_centre_parent_mismatch** — 23 row(s)
- **§ 4_suspected_non_centres** — 40 row(s)
- **§ 5_dead_pages** — 0 row(s)

## §1 Admissions with no program or scope links

| admission_id | name | scope_slug | url |
|---|---|---|---|
| admission--india--phd | Admissions — India — PhD | phd | https://www.srmist.edu.in/admission-india/phd/ |
| admission--international--categories-of-international-students | Admissions — International — Categories of International Students | categories-of-international-students | https://www.srmist.edu.in/admission-international/categories-of-international-students/ |
| admission--international--phd | Admissions — International — PhD | phd | https://www.srmist.edu.in/admission-international/phd/ |
| admission--international--scholarships | Admissions — International — International Scholarships | scholarships | https://www.srmist.edu.in/admission-international/scholarships/ |
| admission--international--science-humanities | Admissions — International — Science & Humanities | science-humanities | https://www.srmist.edu.in/admission-international/science-humanities/ |

## §2 Programs with no `admission_governs` edge

_Total: 140_

### Parent: Aerospace Engineering (3)

| program_id | name |
|---|---|
| program--drone-technology | Minor Degree in Drone Technology |
| program--phd-aerospace-engineering | PhD. Aerospace Engineering (Full Time) |
| program--space-technology | Minor Degree in Space Technology |

### Parent: Agronomy (2)

| program_id | name |
|---|---|
| program--b-sc-hons-agriculture | B.Sc. (Hons.) Agriculture 2026 |
| program--phd-agronomy | PhD. Agronomy |

### Parent: Anaesthesia (1)

| program_id | name |
|---|---|
| program--m-d-anaesthesiology | M.D. Anaesthesiology |

### Parent: Anatomy (1)

| program_id | name |
|---|---|
| program--m-d-anatomy | M.D. Anatomy |

### Parent: Architecture (1)

| program_id | name |
|---|---|
| program--ph-d-in-architecture-and-interior-design | PhD. Architecture and Interior Design |

### Parent: Automobile Engineering (1)

| program_id | name |
|---|---|
| program--ph-d-in-automobile-engineering | PhD. Automobile Engineering |

### Parent: Biochemistry (3)

| program_id | name |
|---|---|
| program--best-m-sc-biochemistry-colleges-chennai | M.Sc. Biochemistry |
| program--m-d-biochemistry | M.D. Biochemistry |
| program--ph-d-in-biochemistry | PhD. Biochemistry |

### Parent: Biomedical Engineering (4)

| program_id | name |
|---|---|
| program--assistive-technology-engineering | Minor Degree in Assistive Technology Engineering |
| program--computer-aided-diagnostics | Minor Degree in Computer-Aided Diagnostics |
| program--medical-device-technology | Minor Degree in Medical Device Technology |
| program--phd-in-biomedical-engineering | PhD. Biomedical Engineering |

### Parent: Biotechnology (3)

| program_id | name |
|---|---|
| program--b-tech-biotechnology | B.Tech Biotechnology Course 2026 |
| program--phd-in-biotechnology | PhD. Biotechnology |
| program--regular-phd | PhD. Biotechnology |

### Parent: Cardio Vascular & Thoracic Surgery (2)

| program_id | name |
|---|---|
| program--b-sc-cardio-perfusion-technology | B.Sc. Cardio Perfusion Technology |
| program--m-ch-cardiothoracic-vascular-surgery | M.Ch. Cardiothoracic and Vascular Surgery |

### Parent: Cardiology (1)

| program_id | name |
|---|---|
| program--d-m-cardiology | D.M. Cardiology |

### Parent: Chemical Engineering (1)

| program_id | name |
|---|---|
| program--ph-d-in-chemical-engineering | PhD. Chemical Engineering |

### Parent: Chemistry (2)

| program_id | name |
|---|---|
| program--best-m-sc-chemistry-colleges-chennai | M.Sc. Chemistry |
| program--ph-d-chemistry | PhD. Chemistry |

### Parent: Civil Engineering (1)

| program_id | name |
|---|---|
| program--ph-d-in-civil-engineeringfull-time | PhD. Civil Engineering (Full Time) |

### Parent: Clinical Psychology (1)

| program_id | name |
|---|---|
| program--ph-d-clinical-psychology | Ph.D. Clinical Psychology |

### Parent: College of Nursing (3)

| program_id | name |
|---|---|
| program--b-sc-nursing | B.Sc. Nursing |
| program--m-sc-paediatric-nursing | M.Sc. Paediatric Nursing |
| program--m-sc-psychiatric-nursing | M.Sc. Psychiatric Nursing |

### Parent: College of Occupational Therapy (2)

| program_id | name |
|---|---|
| program--m-o-t-paediatrics | M.O.T Paediatrics |
| program--ph-d-occupational-therapy | Ph.D. Occupational Therapy |

### Parent: College of Physiotherapy (2)

| program_id | name |
|---|---|
| program--m-p-t-neurology | M.P.T – Neuroscience |
| program--ph-d-physiotherapy | Ph.D. Physiotherapy |

### Parent: Community Medicine (1)

| program_id | name |
|---|---|
| program--m-d-community-medicine | M.D. Community Medicine |

### Parent: Computational Intelligence (4)

| program_id | name |
|---|---|
| program--artificial-intelligence-and-machine-learning | Minor Degree in Artificial Intelligence and Machine Learning |
| program--immersive-technologies-2 | Minor Degree in Immersive Technologies |
| program--m-techintegrated-artificial-intelligence | M.Tech. (Integrated) – Artificial Intelligence |
| program--m-tech-in-artificial-intelligence | M.Tech. Artificial Intelligence |

### Parent: Computer Applications (2)

| program_id | name |
|---|---|
| program--bca-genrative-artificial-intelligence | BCA in Generative AI |
| program--ph-d-in-computer-applications | PhD. Computer Applications |

### Parent: Computer Science (6)

| program_id | name |
|---|---|
| program--best-b-sc-computer-science-colleges-chennai | B.Sc Computer Science degree |
| program--best-m-sc-computer-science-colleges-in-chennai | M.Sc Computer Science in Chennai |
| program--computer-science-and-engineering | Minor Degree in Computer Science and Engineering |
| program--m-tech-computer-science-and-engineering | M.Tech. Computer Science and Engineering |
| program--m-tech-computer-science-engineering | M. Tech Computer Science and Engineering |
| program--ph-d-in-computer-science-and-engineering | PhD. Computer Science and Engineering (Full Time) |

### Parent: Computer Science and Engineering (9)

| program_id | name |
|---|---|
| program--b-tech-computer-science-and-engineering | B.Tech Computer Science Engineering 2026 |
| program--b-tech-cse-with-specialization-in-blockchain-technology | B.Tech CSE Blockchain Technology 2026 |
| program--b-tech-cse-with-specialization-in-cloud-computing | B.Tech CSE Cloud Computing 2026 |
| program--b-tech-cse-with-specialization-in-big-data-analytics | B.Tech CSE Big Data Analytics 2026 |
| program--b-tech-cse-with-specialization-in-gaming-technology | B.Tech CSE Gaming Technology 2026 |
| program--b-tech-cse-with-specialization-in-computer-networking | B.Tech CSE Computer Networking 2026 |
| program--b-tech-cse-with-specialization-in-internet-of-things | B.Tech CSE Internet of Things Course 2026 |
| program--b-tech-cse-with-with-specialization-in-cyber-security | B.Tech CSE Cyber Security 2026 |
| program--full-stack-development | Minor Degree in Full Stack Development |

### Parent: Corporate Secretaryship and Accounting & Finance (2)

| program_id | name |
|---|---|
| program--best-b-com-accounting-finance-colleges-chennai | B.Com. Accounting & Finance |
| program--best-m-com-accounting-finance-colleges-chennai | M.Com. Accounting & Finance |

### Parent: Critical Care Medicine (1)

| program_id | name |
|---|---|
| program--b-sc-critical-care-technology | B.Sc. Critical Care Technology |

### Parent: Data Science And Business Systems (2)

| program_id | name |
|---|---|
| program--b-tech-ece-with-specialization-in-data-sciences | B.Tech ECE Data Science 2026 |
| program--data-science | Minor Degree in Data Science |

### Parent: Defence and Strategic Studies (1)

| program_id | name |
|---|---|
| program--ph-d-in-defence-and-strategic-studies | Ph.D. Defence and Strategic Studies |

### Parent: Economics (2)

| program_id | name |
|---|---|
| program--b-sc-economics | B.Sc. Economics |
| program--ph-d-in-economics | Ph.D. Economics |

### Parent: Electrical and Electronics Engineering (2)

| program_id | name |
|---|---|
| program--electric-vehicle-technology | Minor Degree in Electric Vehicle Technology |
| program--ph-d-in-electrical-electronics-engineering | PhD. Electrical & Electronics Engineering |

### Parent: Electronics & Communication (4)

| program_id | name |
|---|---|
| program--b-tech-ece-with-specialization-in-cyber-physical-systems | Study B.Tech ECE Cyber Physical Systems 2026 |
| program--b-tech-electronics-computer-engineering | Study B.Tech Electronics & Computer Engineering |
| program--embedded-system | Minor Degree in Embedded System |
| program--ph-d-in-electronics-and-communication-engineering | PhD. Electronics and Communication Engineering |

### Parent: Electronics & Instrumentation Engineering (3)

| program_id | name |
|---|---|
| program--minor-degree-in-industrial-automation | Minor Degree in Industrial Automation |
| program--ph-d-in-electronics-and-instrumentation-engineering-part-timeexternal | PhD. Electronics and Instrumentation Engineering – Part Time (External) |
| program--ph-d-in-electronics-and-instrumentation-engineering-full-time | PhD. Electronics and Instrumentation Engineering (Full Time) |

### Parent: English (1)

| program_id | name |
|---|---|
| program--b-a-english-2 | B.A. English |

### Parent: Food Technology (1)

| program_id | name |
|---|---|
| program--ph-d-in-food-process-engineeringfull-time | PhD. Food Process Engineering(Full Time) |

### Parent: Fruit Science (1)

| program_id | name |
|---|---|
| program--phd-fruit-science | PhD. Fruit Science |

### Parent: General Medicine (1)

| program_id | name |
|---|---|
| program--m-d-general-medicine | M.D. General Medicine |

### Parent: Genetic Engineering (1)

| program_id | name |
|---|---|
| program--phd-in-genetic-engineering | PhD. Genetic Engineering (Full Time) |

### Parent: Genetics and Plant breeding (1)

| program_id | name |
|---|---|
| program--phd-genetics-plant-breeding | PhD. Genetics & Plant Breeding |

### Parent: Horticulture (1)

| program_id | name |
|---|---|
| program--b-sc-hons-horticulture | B.Sc (Hons) Horticulture |

### Parent: Journalism And Mass Communication (2)

| program_id | name |
|---|---|
| program--best-m-a-journalism-and-mass-communication-colleges-in-chennai | M.A. Journalism and Mass Communication |
| program--ph-d-journalism-and-mass-communication | Ph.D. Journalism and Mass Communication |

### Parent: Language, Culture and Society (1)

| program_id | name |
|---|---|
| program--ph-d-language-linguistics-and-literature | PhD. Language, Linguistics and Literature – Full Time |

### Parent: Management (3)

| program_id | name |
|---|---|
| program--b-b-a-business-administration | BBA. Business Administration |
| program--b-s-fintech | B.S Fintech |
| program--phd-in-management | PhD. Management |

### Parent: Mathematics and Statistics (2)

| program_id | name |
|---|---|
| program--best-m-sc-mathematics-colleges-chennai | M.Sc. Mathematics |
| program--ph-d-in-mathematics | PhD. Mathematics |

### Parent: Mechanical Engineering (4)

| program_id | name |
|---|---|
| program--additive-manufacturing | Minor Degree in Additive Manufacturing |
| program--electronic-cooling | Minor Degree in Electronic Cooling |
| program--m-tech-integrated-mechanical-engineering | M.Tech. (Integrated) – Mechanical Engineering |
| program--ph-d-in-mechanical-engineering-full-time | PhD. Mechanical Engineering (Full Time) |

### Parent: Mechatronics (9)

| program_id | name |
|---|---|
| program--automation-and-robotics | B.Tech Automation and Robotics |
| program--automation-in-electronics-manufacturing | Minor Degree in Automation in Electronics Manufacturing |
| program--biosustainability | Minor Degree in Biosustainability |
| program--b-tech-mechatronics-engineering | Study B.Tech Mechatronics Engineering 2026 |
| program--green-energy-and-environmental-engineering | Minor Degree in Green Energy and Environmental Engineering |
| program--mechatronics-engineering | Minor Degree in Mechatronics Engineering |
| program--ph-d-in-mechatronics-engineering-full-time | PhD. Mechatronics Engineering (Full Time) |
| program--robotics | Minor Degree in Robotics |
| program--semiconductor-process-engineering | Minor Degree in Semiconductor Process Engineering |

### Parent: Microbiology (1)

| program_id | name |
|---|---|
| program--m-d-microbiology | M.D. Microbiology |

### Parent: Nephrology (1)

| program_id | name |
|---|---|
| program--d-m-nephrology | D.M. Nephrology |

### Parent: Networking And Communications (3)

| program_id | name |
|---|---|
| program--cyber-security | Minor Degree in Cyber Security |
| program--imaging-sciences-and-machine-vision | Minor Degree in Imaging Sciences and Machine Vision |
| program--internet-of-things-iot | Minor Degree in Internet of Things |

### Parent: Obstetrics and Gynaecology (1)

| program_id | name |
|---|---|
| program--m-s-obstetrics-and-gynaecology | M.S. Obstetrics and Gynaecology |

### Parent: Optometry (2)

| program_id | name |
|---|---|
| program--m-optm-optometry | M.Optom (Optometry) |
| program--ph-d-optometry | Ph.D. Optometry |

### Parent: Oral and Maxillofacial Pathology (1)

| program_id | name |
|---|---|
| program--m-d-s-oral-pathology | M.D.S. Oral Pathology |

### Parent: Orthopaedics (1)

| program_id | name |
|---|---|
| program--m-s-orthopaedics | M.S. Orthopaedics |

### Parent: Paediatrics (1)

| program_id | name |
|---|---|
| program--m-d-paediatrics | M.D. Paediatrics |

### Parent: Pathology (1)

| program_id | name |
|---|---|
| program--m-d-pathology | M.D. Pathology |

### Parent: Pharmacology (1)

| program_id | name |
|---|---|
| program--m-d-pharmacology | M.D. Pharmacology |

### Parent: Pharmacy Practice (1)

| program_id | name |
|---|---|
| program--pharmd-doctor-of-pharmacy | Pharm.D. Doctor of Pharmacy |

### Parent: Pharmacy Research (1)

| program_id | name |
|---|---|
| program--ph-d-in-pharmacy | PhD. Pharmacy |

### Parent: Physics and Nanotechnology (5)

| program_id | name |
|---|---|
| program--best-m-sc-physics-colleges-in-chennai | M.Sc. Physics |
| program--minor-degree-in-quantum-technologies | Minor Degree in Quantum Technologies |
| program--ph-d-in-nanotechnology-full-time | PhD. Nanotechnology (Full Time) |
| program--ph-d-in-physics-full-time | PhD. Physics (Full Time) |
| program--semiconductor-technology | Minor Degree in Semiconductor Technology |

### Parent: Physiology (1)

| program_id | name |
|---|---|
| program--m-d-physiology | M.D. Physiology |

### Parent: Psychiatry (1)

| program_id | name |
|---|---|
| program--m-d-psychiatry | M.D. Psychiatry |

### Parent: Psychology (1)

| program_id | name |
|---|---|
| program--ph-d-in-psychology | PhD. Psychology |

### Parent: Respiratory Medicine (1)

| program_id | name |
|---|---|
| program--m-d-respiratory-medicine | M.D. Respiratory Medicine |

### Parent: School of Education (8)

| program_id | name |
|---|---|
| program--b-ed-commerce-accounting | B.Ed. Commerce & Accounting |
| program--b-ed-computer-science | B.Ed. Computer Science |
| program--b-ed-economics | B.Ed. Economics |
| program--b-ed-english | B.Ed. English |
| program--b-ed-mathematics | B.Ed. Mathematics |
| program--b-ed-physical-science | B.Ed. Physical Science |
| program--b-ed-social-science | B.Ed. Social Science |
| program--b-ed-tamil | B.Ed. Tamil |

### Parent: School of Public Health (2)

| program_id | name |
|---|---|
| program--integrated-master-of-public-health | MPH (Integrated) – Public Health |
| program--ph-d-public-health | PhD. Public Health |

### Parent: Social Work (1)

| program_id | name |
|---|---|
| program--phd-in-social-work | PhD. Social Work |

### Parent: Tamil (1)

| program_id | name |
|---|---|
| program--ph-d-in-tamil | Ph.D. Tamil |

### Parent: Visual Communication (2)

| program_id | name |
|---|---|
| program--best-b-sc-visual-communication-degree-in-chennai | B.Sc. Visual Communication |
| program--ph-d-visual-communication | Ph.D. Visual Communication |

### Parent: Yoga (1)

| program_id | name |
|---|---|
| program--ph-d-in-yoga | Ph.D. Yoga |

## §3 Centres with mismatched primary parent

| centre_id | current_parent | observed_parents | centre_url |
|---|---|---|---|
| centre--srm-dbt-platform | Faculty of Engineering & Technology | Biotechnology | https://www.srmist.edu.in/lab/srm-dbt-platform/ |
| centre--accelerated-computing | Computational Intelligence | Computing Technologies | https://www.srmist.edu.in/lab/accelerated-computing/ |
| centre--advance-multilingual-computing | Computational Intelligence | Computing Technologies | https://www.srmist.edu.in/lab/advance-multilingual-computing/ |
| centre--center-for-acces | College of Occupational Therapy | Electronics & Instrumentation Engineering | https://www.srmist.edu.in/lab/center-for-acces/ |
| centre--clinical-departments | SRM Medical College Hospital and Research Centre (SRM MCHRC) | College of Occupational Therapy | https://www.srmist.edu.in/lab/clinical-departments/ |
| centre--control-energy-testing-lab | Electronics & Instrumentation Engineering | Electrical and Electronics Engineering | https://www.srmist.edu.in/lab/control-energy-testing-lab/ |
| centre--edge-intelligence-lab | Computational Intelligence | Networking And Communications | https://www.srmist.edu.in/lab/edge-intelligence-lab/ |
| centre--embedded-ai-lab-associated-with-nvidia-gtc | Electronics & Communication | Networking And Communications | https://www.srmist.edu.in/lab/embedded-ai-lab-associated-with-nvidia-gtc/ |
| centre--facilities-for-differently-abled-divyangjan-barrier-free-environment | College of Occupational Therapy | College of Pharmacy | https://www.srmist.edu.in/lab/facilities-for-differently-abled-divyangjan-barrier-free-environment/ |
| centre--green-computing | Data Science And Business Systems | Computing Technologies | https://www.srmist.edu.in/lab/green-computing/ |
| centre--hand-rehabilitation-lab-2 | College of Occupational Therapy | College of Physiotherapy | https://www.srmist.edu.in/lab/hand-rehabilitation-lab-2/ |
| centre--hand-rehabilitation-lab | Faculty of Management | College of Occupational Therapy | https://www.srmist.edu.in/lab/hand-rehabilitation-lab/ |
| centre--neurology-lab | College of Physiotherapy | College of Occupational Therapy | https://www.srmist.edu.in/lab/neurology-lab/ |
| centre--neuro-rehabilitation-lab | College of Occupational Therapy | College of Physiotherapy | https://www.srmist.edu.in/lab/neuro-rehabilitation-lab/ |
| centre--nutrition-lab | Clinical Nutrition and Dietetics | College of Nursing | https://www.srmist.edu.in/lab/nutrition-lab/ |
| centre--obstetrics-and-gynecology-lab | College of Nursing | College of Physiotherapy | https://www.srmist.edu.in/lab/obstetrics-and-gynecology-lab/ |
| centre--orthopaedic-lab | College of Physiotherapy | College of Occupational Therapy | https://www.srmist.edu.in/lab/orthopaedic-lab/ |
| centre--post-graduate-research-lab | Directorate of Research | College of Physiotherapy | https://www.srmist.edu.in/lab/post-graduate-research-lab/ |
| centre--quantum-computing | Computational Intelligence | Computing Technologies | https://www.srmist.edu.in/lab/quantum-computing/ |
| centre--spdc | Directorate of Learning and Development | Electrical and Electronics Engineering | https://www.srmist.edu.in/lab/spdc/ |
| centre--theoretical-computer-science | Computational Intelligence | Computing Technologies | https://www.srmist.edu.in/lab/theoretical-computer-science/ |
| centre--visual-computing | Computational Intelligence | Computing Technologies | https://www.srmist.edu.in/lab/visual-computing/ |
| centre--wireless-charging-research-center | Electronics & Communication | Electrical and Electronics Engineering | https://www.srmist.edu.in/lab/wireless-charging-research-center/ |

## §4 Suspected non-centres (mis-typed as centre)

| centre_id | name | suggested_type | reason | url |
|---|---|---|---|---|
| centre--reach | REACH | misc | no centre/lab/facility token in name | https://www.srmist.edu.in/research/research-wings/reach/ |
| centre--scif | SCIF | misc | no centre/lab/facility token in name | https://www.srmist.edu.in/research/scif/ |
| centre--extension-activities-and-outreach-programs | Extension Activities and Outreach Programs | misc | non-centre token in name | https://www.srmist.edu.in/department/college-of-nursing/extension-activities-and-outreach-programs/ |
| centre--extension-activities-and-community-outreach-programs | Extension Activities and Community Outreach Programs | misc | non-centre token in name | https://www.srmist.edu.in/department/college-of-occupational-therapy/extension-activities-and-community-outreach-programs/ |
| centre--accelerated-computing | Accelerated Computing | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/accelerated-computing/ |
| centre--advance-multilingual-computing | Advance Multilingual Computing | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/advance-multilingual-computing/ |
| centre--aerospace-hangar | Aerospace Hangar | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/aerospace-hangar/ |
| centre--agricultural-microbiology-and-environmental-science | Agricultural Microbiology and Environmental Science | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/agricultural-microbiology-and-environmental-science/ |
| centre--carpentry-shop | Carpentry Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/carpentry-shop/ |
| centre--chemistry-research-facilities | Chemistry Research Facilities | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/chemistry-research-facilities/ |
| centre--clinical-departments | Clinical Departments | misc | non-centre token in name | https://www.srmist.edu.in/lab/clinical-departments/ |
| centre--construction-yard | Construction yard | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/construction-yard/ |
| centre--data-mining | Data Mining | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/data-mining/ |
| centre--display-hall | Display Hall | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/display-hall/ |
| centre--dst-fist | DST-FIST | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/dst-fist/ |
| centre--edit-suite | Edit Suite | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/edit-suite/ |
| centre--electronics-manufacturing-services | Electronics Manufacturing Services | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/electronics-manufacturing-services/ |
| centre--electronic-design-automation | Electronic Design Automation | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/electronic-design-automation/ |
| centre--facilities-for-differently-abled-divyangjan-barrier-free-environment | Facilities for Differently-Abled (Divyangjan): Barrier-Free Environment | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/facilities-for-differently-abled-divyangjan-barrier-free-environment/ |
| centre--fitting-shop | Fitting Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/fitting-shop/ |
| centre--functional-materials-and-energy-devices-research | Functional Materials and Energy Devices Research | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/functional-materials-and-energy-devices-research/ |
| centre--green-computing | Green Computing | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/green-computing/ |
| centre--instruments | Instruments | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/instruments/ |
| centre--machine-shop | Machine Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/machine-shop/ |
| centre--operating-system | Operating System | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/operating-system/ |
| centre--pharmaceutical-chemistry | Pharmaceutical Chemistry | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/pharmaceutical-chemistry/ |
| centre--pharmaceutics | Pharmaceutics | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/pharmaceutics/ |
| centre--pharmacognosy | Pharmacognosy | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/pharmacognosy/ |
| centre--quantum-computing | Quantum Computing | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/quantum-computing/ |
| centre--recording-theatre | Recording Theatre | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/recording-theatre/ |
| centre--research-and-development | Research and Development | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/research-and-development/ |
| centre--sheet-metal-shop | Sheet Metal Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/sheet-metal-shop/ |
| centre--smithy-shop | Smithy Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/smithy-shop/ |
| centre--soil-science-and-agricultural-chemistry | Soil Science and Agricultural Chemistry | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/soil-science-and-agricultural-chemistry/ |
| centre--srm-brin | SRM-BRIN | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/srm-brin/ |
| centre--theoretical-computer-science | Theoretical Computer Science | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/theoretical-computer-science/ |
| centre--transgenic-green-house-built-as-per-the-specifications-of-the-dbt-govt-of-india | Transgenic Green House (built as per the specifications of the DBT, Govt of India) | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/transgenic-green-house-built-as-per-the-specifications-of-the-dbt-govt-of-india/ |
| centre--transgenic-green-house | Transgenic Green House | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/transgenic-green-house/ |
| centre--visual-computing | Visual Computing | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/visual-computing/ |
| centre--welding-shop | Welding Shop | facility | no centre/lab/facility token in name | https://www.srmist.edu.in/lab/welding-shop/ |

## §5 Dead / thin centre pages

_none_
